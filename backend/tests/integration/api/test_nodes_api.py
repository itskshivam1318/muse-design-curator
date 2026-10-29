"""Plugin nodes on a board: create, edit, run, and the run's outputs written back."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo, events
from app.db.models import BoardItem, ItemAttribute
from app.explore.visualize import recover_stuck
from tests.media import image_bytes


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    from app.api import deps

    s = deps._factory()()
    yield s
    s.close()


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "Chairs"}).json()["id"]  # type: ignore[no-any-return]


def error(r: Any) -> str:
    return r.json()["error"]["code"]  # type: ignore[no-any-return]


def add_plugin(client: TestClient, board: str, plugin_id: str) -> None:
    assert (
        client.post(f"/api/boards/{board}/plugins", json={"plugin_id": plugin_id}).status_code
        == 200
    )


def upload_image(client: TestClient, board: str, seed: int = 0) -> str:
    r = client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", (f"{seed}.png", image_bytes(size=(320, 256), seed=seed), "image/png"))],
    )
    return r.json()["results"][0]["item"]["id"]  # type: ignore[no-any-return]


def make_note(client: TestClient, board: str, text: str = "softer edges") -> str:
    r = client.post(f"/api/boards/{board}/notes", json={"text": text, "x": 0, "y": 0})
    return r.json()["id"]  # type: ignore[no-any-return]


def make_node(
    client: TestClient,
    board: str,
    plugin_id: str,
    inputs: list[str],
    x: float = 500,
    y: float = 100,
) -> dict[str, Any]:
    r = client.post(
        f"/api/boards/{board}/nodes",
        json={"plugin_id": plugin_id, "x": x, "y": y, "input_item_ids": inputs},
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def run_node(client: TestClient, node_id: str) -> dict[str, Any]:
    r = client.post(f"/api/nodes/{node_id}/run")
    assert r.status_code == 202, r.text
    return client.get(f"/api/plugin-runs/{r.json()['id']}").json()  # type: ignore[no-any-return]


def test_create_node_requires_added_plugin(client: TestClient, board: str) -> None:
    r = client.post(
        f"/api/boards/{board}/nodes",
        json={"plugin_id": "palette", "x": 1, "y": 2, "input_item_ids": []},
    )
    assert r.status_code == 400 and error(r) == "PLUGIN_NOT_ADDED"
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [], x=1, y=2)
    assert node["id"].startswith("node_")
    assert {k: node[k] for k in ("board_id", "plugin_id", "x", "y", "w", "h")} == {
        "board_id": board, "plugin_id": "palette", "x": 1, "y": 2, "w": 300, "h": 360,
    }  # fmt: skip
    assert node["input_item_ids"] == [] and node["params"] == {"count": 5}
    assert node["last_run_id"] is None


def test_node_crud(client: TestClient, board: str) -> None:
    add_plugin(client, board, "palette")
    img = upload_image(client, board)
    node = make_node(client, board, "palette", [])
    r = client.patch(
        f"/api/nodes/{node['id']}", json={"x": 9, "input_item_ids": [img], "params": {"count": 4}}
    )
    assert r.status_code == 200
    assert (r.json()["x"], r.json()["y"]) == (9, 100)
    assert r.json()["input_item_ids"] == [img] and r.json()["params"] == {"count": 4}
    bad = client.patch(f"/api/nodes/{node['id']}", json={"params": {"count": 99}})
    assert bad.status_code == 400 and error(bad) == "PLUGIN_BAD_INPUT"
    ghost = client.patch(f"/api/nodes/{node['id']}", json={"input_item_ids": ["item_nope"]})
    assert ghost.status_code == 400
    listed = client.get(f"/api/boards/{board}/nodes").json()
    assert [n["id"] for n in listed["nodes"]] == [node["id"]] and listed["runs"] == {}
    assert client.delete(f"/api/nodes/{node['id']}").status_code == 204
    assert client.get(f"/api/boards/{board}/nodes").json()["nodes"] == []
    assert client.patch(f"/api/nodes/{node['id']}", json={"x": 1}).status_code == 404
    assert client.post(f"/api/nodes/{node['id']}/run").status_code == 404


def test_run_palette_end_to_end_writes_note_and_attributes(
    client: TestClient, board: str, db: Session
) -> None:
    add_plugin(client, board, "palette")
    img = upload_image(client, board)
    node = make_node(client, board, "palette", [img], x=500, y=100)
    with events.subscribe(board) as sub:
        run = run_node(client, node["id"])
        seen = []
        while (ev := sub.get(timeout=1)) is not None:
            seen.append(ev["type"])
            if ev["type"] == "plugin_run.done":
                assert ev["data"]["node_id"] == node["id"] and ev["data"]["run_id"] == run["id"]
                assert ev["data"]["output"] == run["output"]
                break
    assert seen[0] == "plugin_run.queued" and "plugin_run.progress" in seen
    assert seen.index("item.added") < seen.index("plugin_run.done")
    assert run["status"] == "done" and run["error_code"] is None and run["finished_at"]
    assert set(run) == {"id", "node_id", "plugin_id", "status", "progress", "output",
                        "error_code", "error_message", "created_at", "finished_at"}  # fmt: skip
    (note_id,) = run["output"]["created_item_ids"]
    assert run["output"]["skipped_attributes"] == []
    note = db.get(BoardItem, note_id)
    assert note is not None and note.kind == "note"
    assert (note.note_text or "").startswith("Palette:")
    assert (note.x, note.y) == (500 + 300 + 40, 100)
    attr = db.scalar(
        select(ItemAttribute).where(ItemAttribute.item_id == img, ItemAttribute.key == "palette")
    )
    assert attr is not None and str(attr.value_json).startswith("#")
    assert (attr.source, attr.source_detail, attr.category, attr.kind) == (
        "plugin", "palette", "plugin", "text",
    )  # fmt: skip
    assert attr.confidence == 1.0 and attr.status == "extracted"
    history = client.get(f"/api/items/{img}/attributes/palette/history").json()["events"]
    assert [(e["actor"], e["action"]) for e in history] == [("plugin", "plugin")]
    listed = client.get(f"/api/boards/{board}/nodes").json()
    assert listed["nodes"][0]["last_run_id"] == run["id"]
    assert listed["runs"][node["id"]]["status"] == "done"


def test_run_image_plugin_creates_generated_items_with_lineage(
    client: TestClient, board: str, db: Session
) -> None:
    add_plugin(client, board, "image")
    img = upload_image(client, board)
    note = make_note(client, board, "rounder arms")
    node = make_node(client, board, "image", [note, img], x=0, y=0)
    client.patch(f"/api/nodes/{node['id']}", json={"params": {"mode": "whole", "count": 2}})
    run = run_node(client, node["id"])
    assert run["status"] == "done", run
    ids = run["output"]["created_item_ids"]
    assert len(ids) == 2
    items = [db.get(BoardItem, i) for i in ids]
    for it in items:
        assert it is not None
        assert (it.kind, it.origin, it.rights_status) == ("image", "generated", "generated")
        assert it.parent_item_id == img
        assert it.generation_json == {
            "plugin": "image", "model": "Muse Spark · Baseten", "run_id": run["id"],
        }  # fmt: skip
        assert it.x == 0 + 300 + 40
    a, b = items
    assert a is not None and b is not None
    assert a.y == 0 and b.y == a.h + 24
    # plugin outputs are never checked: startup recovery must not mark them interrupted
    assert recover_stuck(db) == 0
    db.commit()
    db.refresh(a)
    assert a.check_json is None


def test_failed_run_event_and_rerun_allowed(client: TestClient, board: str) -> None:
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [])  # palette needs at least one image
    with events.subscribe(board) as sub:
        run = run_node(client, node["id"])
        failed = None
        while (ev := sub.get(timeout=1)) is not None:
            if ev["type"] == "plugin_run.failed":
                failed = ev["data"]
                break
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_BAD_INPUT"
    assert run["error_message"] and run["finished_at"]
    assert failed is not None and failed["node_id"] == node["id"] and failed["run_id"] == run["id"]
    assert failed["error_code"] == "PLUGIN_BAD_INPUT"
    again = run_node(client, node["id"])
    assert again["id"] != run["id"] and again["status"] == "failed"


def test_not_connected_plugin_run_400(client: TestClient, board: str) -> None:
    add_plugin(client, board, "video")
    node = make_node(client, board, "video", [])
    r = client.post(f"/api/nodes/{node['id']}/run")
    assert r.status_code == 400 and error(r) == "PLUGIN_NOT_CONNECTED"


def test_unknown_run_404(client: TestClient) -> None:
    assert client.get("/api/plugin-runs/prun_nope").status_code == 404
    assert client.get("/api/boards/nope/nodes").status_code == 404


def test_nodes_404_when_plugins_disabled(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [])
    monkeypatch.setenv("PLUGINS_ENABLED", "0")
    assert client.get(f"/api/boards/{board}/nodes").status_code == 404
    assert client.post(f"/api/nodes/{node['id']}/run").status_code == 404
    assert client.patch(f"/api/nodes/{node['id']}", json={"x": 1}).status_code == 404


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)


def test_demo_mode_run_requires_unlock(demo_on: None, client: TestClient) -> None:
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    board = client.post("/api/boards", json={"title": "B"}).json()["id"]
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [])
    client.cookies.clear()
    r = client.post(f"/api/nodes/{node['id']}/run")
    assert r.status_code == 403 and error(r) == "DEMO_LOCKED"
    assert client.get(f"/api/boards/{board}/nodes").status_code == 200
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    assert client.post(f"/api/nodes/{node['id']}/run").status_code == 202
