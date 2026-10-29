"""Writing a plugin's output back onto the board."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import jobs
from app.db.models import ItemAttribute, PluginNode, PluginRun
from app.db.repos import attributes as attrs_repo
from app.domain.attributes import AttributeRecord
from app.extraction.merge import merge_extraction
from app.plugins.writeback import apply_output
from app.runs.orchestrator import source_records
from tests.integration.api.test_nodes_api import (
    add_plugin,
    make_node,
    upload_image,
)


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
        {"item_id": img, "key": "confirmed_one"},
        {"item_id": img, "key": "edited_one"},
        {"item_id": img, "key": "user_src"},
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
