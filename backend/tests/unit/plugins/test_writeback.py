"""Writing a plugin's output back onto the board."""

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import jobs
from app.db.models import BoardItem, ItemAttribute, PluginNode, PluginRun
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import lenses as lenses_repo
from app.domain.attributes import AttributeRecord
from app.domain.kinds import EnumSpec
from app.domain.lens import load_curated_lens
from app.extraction.merge import merge_extraction
from app.plugins.writeback import apply_output
from app.runs.orchestrator import source_records
from tests.integration.api.test_nodes_api import (
    add_plugin,
    make_node,
    upload_image,
)
from tests.media import image_bytes


@pytest.fixture
def no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: None)


def setup(
    client: TestClient, board: str, db: Session, plugin: str
) -> tuple[str, PluginRun, PluginNode]:
    add_plugin(client, board, plugin)
    img = upload_image(client, board)
    n = make_node(client, board, plugin, [img])
    node = db.get(PluginNode, n["id"])
    assert node is not None
    run = PluginRun(board_id=board, node_id=node.id, plugin_id=plugin,
                    input_item_ids_json=[img], params_json={}, status="running")  # fmt: skip
    db.add(run)
    db.flush()
    return img, run, node


def attr(db: Session, item_id: str, key: str) -> ItemAttribute:
    row = next(r for r in attrs_repo.for_item(db, item_id) if r.key == key)
    return row


def test_writeback_skips_user_edited_attribute(
    client: TestClient, board: str, db: Session, no_jobs: None
) -> None:
    img, run, node = setup(client, board, db, "palette")
    base = {"label": "X", "category": "c", "kind": "text", "confidence": 1.0}
    attrs_repo.upsert(
        db, img, "edited_one", value_json="mine", status="edited", source="user", **base
    )
    attrs_repo.upsert(
        db, img, "user_src", value_json="u", status="extracted", source="user", **base
    )
    attrs_repo.upsert(db, img, "confirmed_one", value_json="c", status="confirmed", source="model", **base)  # fmt: skip
    attrs_repo.upsert(db, img, "model_one", value_json="old", status="extracted", source="model", **base)  # fmt: skip
    out = {"attributes": [
        {"item_id": img, "key": k, "value": "plugin says"}
        for k in ("edited_one", "user_src", "confirmed_one", "model_one")
    ]}  # fmt: skip
    res = apply_output(db, run, node, out)
    assert sorted(res["skipped_attributes"], key=lambda s: s["key"]) == [
        {"item_id": img, "key": "confirmed_one", "reason": "set by you"},
        {"item_id": img, "key": "edited_one", "reason": "set by you"},
        {"item_id": img, "key": "user_src", "reason": "set by you"},
    ]
    assert attr(db, img, "edited_one").value_json == "mine"
    assert attr(db, img, "user_src").value_json == "u"
    assert attr(db, img, "confirmed_one").value_json == "c"
    m = attr(db, img, "model_one")
    assert (m.value_json, m.source, m.source_detail) == ("plugin says", "plugin", "palette")
    assert m.label == "X"  # an existing label is kept when the plugin gives none


def test_writeback_kinds_lists_and_llm_confidence(
    client: TestClient, board: str, db: Session, no_jobs: None
) -> None:
    img, run, node = setup(client, board, db, "critique")
    vals: list[tuple[str, Any]] = [("flag", True), ("count", 3), ("ratio", 0.5),
                                   ("tags", ["#fff", "#000"]), ("name", "oak")]  # fmt: skip
    out = {"attributes": [{"item_id": img, "key": k, "value": v} for k, v in vals]
           + [{"item_id": img, "key": "sure", "value": "x", "label": "Sure", "confidence": 0.9},
              {"item_id": img, "key": "unsure", "value": "y", "confidence": 0.3}]}  # fmt: skip
    apply_output(db, run, node, out)
    got = {r.key: r for r in attrs_repo.for_item(db, img)}
    assert {k: (got[k].kind, got[k].value_json) for k, _ in vals} == {
        "flag": ("boolean", True), "count": ("number", 3), "ratio": ("number", 0.5),
        "tags": ("text", "#fff, #000"), "name": ("text", "oak"),
    }  # fmt: skip
    assert got["name"].confidence == 0.7 and got["name"].status == "extracted"
    assert got["name"].label == "Name" and got["name"].category == "plugin"
    assert (got["sure"].confidence, got["sure"].label) == (0.9, "Sure")
    assert (got["unsure"].confidence, got["unsure"].status) == (0.3, "uncertain")


def test_reextraction_keeps_plugin_attribute(
    client: TestClient, board: str, db: Session, no_jobs: None
) -> None:
    img, run, node = setup(client, board, db, "palette")
    apply_output(
        db, run, node, {"attributes": [{"item_id": img, "key": "palette", "value": "#111"}]}
    )
    row = attr(db, img, "palette")
    rec = AttributeRecord(key="palette", label="Palette", category="color", kind="text",
                          value="#999", confidence=0.9, status="extracted", source="model")  # fmt: skip
    rows, evs = merge_extraction([row], [rec])
    assert rows == [{"key": "palette", "model_value_json": "#999", "model_confidence": 0.9}]
    assert [e["action"] for e in evs] == ["model_suppressed"]
    # the variation engine reads stored rows back as records: a plugin source must validate
    assert [r.source for r in source_records(db, img)] == ["plugin"]


def test_existing_row_keeps_label_category_kind_and_skips_unfit_values(
    client: TestClient, board: str, db: Session, no_jobs: None
) -> None:
    lens = load_curated_lens("fashion", shape_enabled=False)
    assert lens is not None
    closed = next(
        a for a in lens.attributes
        if isinstance(a, EnumSpec) and a.vocabulary and not a.open_vocabulary
    )  # fmt: skip
    row = lenses_repo.save(db, board, "fashion", "edited", lens.model_dump(mode="json"),
                           status="confirmed")  # fmt: skip
    boards_repo.update(db, board, lens_id=row.id)
    img, run, node = setup(client, board, db, "palette")
    rows = {"n": "number", "b": "boolean", "c": "color", "t": "text", closed.key: "enum",
            "open_enum": "enum"}  # fmt: skip
    for key, kind in rows.items():
        attrs_repo.upsert(db, img, key, label=f"L{key}", category="lensy", kind=kind,
                          value_json=None, confidence=0.5, status="extracted",
                          source="model")  # fmt: skip
    good = {"n": 4, "b": False, "c": "#A1B2C3", "t": "linen", closed.key: closed.vocabulary[0],
            "open_enum": "anything"}  # fmt: skip
    bad = {"n": True, "b": "yes", "c": "teal", "t": 3, closed.key: "not_an_option_zz"}
    for key, value in good.items():
        res = apply_output(db, run, node, {"attributes": [{"item_id": img, "key": key,
                                                           "value": value, "label": "New"}]})  # fmt: skip
        assert res["skipped_attributes"] == [], key
        r = attr(db, img, key)
        assert (r.label, r.category, r.kind) == (f"L{key}", "lensy", rows[key])
        assert r.source == "plugin" and r.value_json == (value.lower() if key == "c" else value)
    for key, value in bad.items():
        res = apply_output(
            db, run, node, {"attributes": [{"item_id": img, "key": key, "value": value}]}
        )
        (skip,) = res["skipped_attributes"]
        assert (skip["item_id"], skip["key"]) == (img, key) and rows[key] in skip["reason"]
        assert attr(db, img, key).value_json == (good[key].lower() if key == "c" else good[key])


def test_parent_is_first_live_image_input(
    client: TestClient, board: str, db: Session, no_jobs: None
) -> None:
    _img, run, node = setup(client, board, db, "image")
    second = upload_image(client, board, 5)
    first = run.input_item_ids_json[0]
    run.input_item_ids_json = [first, second]
    removed = db.get(BoardItem, first)
    assert removed is not None
    removed.removed_at = "2026-10-29T00:00:00.000+00:00"
    db.flush()
    data = base64.b64encode(image_bytes(size=(320, 256))).decode()
    res = apply_output(db, run, node, {"images": [{"data_b64": data, "caption": "x"}]})
    (item_id,) = res["created_item_ids"]
    item = db.get(BoardItem, item_id)
    assert item is not None and item.parent_item_id == second
