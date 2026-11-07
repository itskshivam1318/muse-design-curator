"""Option grid for batch outputs; keep and clear."""

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events, jobs
from app.db.models import BoardItem, PluginNode, PluginRun
from app.plugins.runners import PluginError
from app.plugins.writeback import apply_output, grid_cells
from tests.integration.api.test_nodes_api import (
    make_node,
    upload_image,
)
from tests.media import image_bytes
from tests.unit.plugins.test_runners import img, py_plugin, run
from tests.unit.plugins.test_writeback import setup


@pytest.fixture
def no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: None)


def png_b64(seed: int) -> str:
    return base64.b64encode(image_bytes(size=(320, 256), seed=seed)).decode()


def test_grid_cells_four_wide() -> None:
    assert grid_cells(6, (100, 80)) == [
        (0, 0), (124, 0), (248, 0), (372, 0), (0, 104), (124, 104),
    ]  # fmt: skip


def overlap(a: BoardItem, b: BoardItem) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_batch_outputs_are_options_in_grid(
    client: TestClient,
    board: str,
    db: Session,
    no_jobs: None,
) -> None:
    _img, r, node = setup(client, board, db, "palette")
    out = apply_output(db, r, node, {"images": [{"data_b64": png_b64(i)} for i in range(6)]})
    ids = out["option_item_ids"]
    assert ids == out["created_item_ids"] and len(ids) == 6
    items = [db.get(BoardItem, i) for i in ids]
    assert all(i is not None and i.option_run_id == r.id for i in items)
    others = list(db.scalars(select(BoardItem).where(BoardItem.id.not_in(ids))))
    for n, a in enumerate(items):
        assert a is not None
        assert not any(overlap(a, b) for b in items[n + 1 :] if b is not None)
        assert not any(overlap(a, b) for b in others)


def test_single_output_not_option(
    client: TestClient,
    board: str,
    db: Session,
    no_jobs: None,
) -> None:
    _, r, node = setup(client, board, db, "palette")
    out = apply_output(db, r, node, {"images": [{"data_b64": png_b64(1)}]})
    assert out["option_item_ids"] == []
    assert db.get(BoardItem, out["created_item_ids"][0]).option_run_id is None  # type: ignore[union-attr]


def six_options(
    client: TestClient, board: str, db: Session, node_id: str, run_id: str
) -> list[str]:
    node = db.get(PluginNode, node_id)
    r = db.get(PluginRun, run_id)
    assert node and r
    out = apply_output(db, r, node, {"images": [{"data_b64": png_b64(i)} for i in range(6)]})
    db.commit()
    return list(out["option_item_ids"])


def test_keep_option_clears_flag(
    client: TestClient,
    board: str,
    db: Session,
    no_jobs: None,
) -> None:
    _, r, node = setup(client, board, db, "palette")
    ids = six_options(client, board, db, node.id, r.id)
    res = client.post(f"/api/items/{ids[0]}/keep-option")
    assert res.status_code == 200 and res.json()["option_run_id"] is None
    assert client.post(f"/api/items/{ids[0]}/keep-option").status_code == 404


def test_keep_non_option_404(client: TestClient, board: str) -> None:
    item = upload_image(client, board)
    assert client.post(f"/api/items/{item}/keep-option").status_code == 404


def test_clear_options_removes_only_flagged(
    client: TestClient,
    board: str,
    db: Session,
    no_jobs: None,
) -> None:
    _, r, node = setup(client, board, db, "palette")
    node.last_run_id = r.id
    old = PluginRun(board_id=board, node_id=node.id, plugin_id="palette",
                    input_item_ids_json=[], params_json={}, status="done")  # fmt: skip
    db.add(old)
    db.flush()
    older = six_options(client, board, db, node.id, old.id)  # an earlier run's options stay
    ids = six_options(client, board, db, node.id, r.id)
    other_img = upload_image(client, board, seed=5)
    other = make_node(client, board, "palette", [other_img])
    r2 = PluginRun(board_id=board, node_id=other["id"], plugin_id="palette",
                   input_item_ids_json=[other_img], params_json={}, status="running")  # fmt: skip
    db.add(r2)
    db.flush()
    theirs = six_options(client, board, db, other["id"], r2.id)
    for i in ids[:2]:
        assert client.post(f"/api/items/{i}/keep-option").status_code == 200
    res = client.post(f"/api/nodes/{node.id}/clear-options")
    assert res.status_code == 200
    assert sorted(res.json()["removed_item_ids"]) == sorted(ids[2:])
    db.expire_all()
    assert all(db.get(BoardItem, i).removed_at is None for i in ids[:2] + theirs + older)  # type: ignore[union-attr]
    assert all(db.get(BoardItem, i).removed_at is not None for i in ids[2:])  # type: ignore[union-attr]


def test_python_25_images_rejected(tmp_path: Path) -> None:
    body = (
        "from PIL import Image\n"
        "def run(inputs, params, ctx):\n"
        "    Image.new('RGB', (4, 4)).save('o.png')\n"
        "    return {'images': [{'path': 'o.png'}] * 25}\n"
    )
    p = py_plugin(tmp_path, body, outputs=["images"])
    with pytest.raises(PluginError) as e:
        run(p, [img()])
    assert e.value.code == "PLUGIN_BAD_OUTPUT"
    ok = py_plugin(tmp_path / "ok", body.replace("* 25", "* 24"), outputs=["images"])
    assert len(run(ok, [img()])["images"]) == 24


def test_clear_publishes_removed_and_restore_brings_option_back(
    client: TestClient, board: str, db: Session, no_jobs: None
) -> None:
    _, r, node = setup(client, board, db, "palette")
    node.last_run_id = r.id
    ids = six_options(client, board, db, node.id, r.id)
    with events.subscribe(board) as sub:
        res = client.post(f"/api/nodes/{node.id}/clear-options")
        seen = []
        while len(seen) < 6 and (ev := sub.get(timeout=1)) is not None:
            if ev["type"] == "item.removed":
                seen.append(ev["data"]["id"])
    assert sorted(res.json()["removed_item_ids"]) == sorted(ids)
    assert sorted(seen) == sorted(ids)
    listed = client.get(f"/api/boards/{board}/items").json()
    assert not {i["id"] for i in listed["items"]} & set(ids)
    back = client.post(f"/api/items/{ids[0]}/restore")
    assert back.status_code == 200 and back.json()["option_run_id"] == r.id
    listed = client.get(f"/api/boards/{board}/items").json()
    assert ids[0] in {i["id"] for i in listed["items"]}


def test_restore_live_item_404(client: TestClient, board: str) -> None:
    item = upload_image(client, board)
    assert client.post(f"/api/items/{item}/restore").status_code == 404
    assert client.post("/api/items/nope/restore").status_code == 404


def test_clear_options_unknown_node_404(client: TestClient) -> None:
    assert client.post("/api/nodes/nope/clear-options").status_code == 404


def test_options_inherit_the_parents_subject_and_cleanup_prompts_sam_with_it(
    client: TestClient, board: str, db: Session, no_jobs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.analysis import locate as locate_mod
    from app.providers.segmentation import MockSegmentationProvider

    img_id, r, node = setup(client, board, db, "palette")
    parent = db.get(BoardItem, img_id)
    assert parent is not None
    parent.subject = "lounge chair"
    db.commit()
    ids = six_options(client, board, db, node.id, r.id)
    option = db.get(BoardItem, ids[0])
    assert option is not None and option.subject == "lounge chair"
    assert option.parse_status == "completed"

    nouns: list[str] = []

    class Seg(MockSegmentationProvider):
        def localize(self, image: bytes, sha256: str, noun: str):  # type: ignore[no-untyped-def]
            nouns.append(noun)
            return super().localize(image, sha256, noun)

    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: Seg())
    locate_mod.locate_object(db, option.id)
    assert nouns == ["lounge chair"]


def test_model_item_is_completed_and_never_queued_for_analysis(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, r, node = setup(client, board, db, "palette")
    queued: list[str] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append(name))
    out = apply_output(
        db, r, node,
        {"model3d": [{"glb": b"glTF" + b"\x02\x00\x00\x00", "poster": image_bytes(seed=2)}]},
    )  # fmt: skip
    item = db.get(BoardItem, out["created_item_ids"][0])
    assert item is not None and item.kind == "model" and item.parse_status == "completed"
    db.commit()
    assert "analyse_item" not in queued
