from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from app import demo, events
from app.agent import tools
from app.agent.context import ToolContext, next_slot
from app.ingest import links
from tests.media import image_bytes


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(links, "resolver", lambda host: ["93.184.216.34"])


def _item(x: float, y: float = 0, w: float = 100, h: float = 80) -> dict[str, Any]:
    return {"x": x, "y": y, "w": w, "h": h}


def test_next_slot_rows_of_four() -> None:
    assert next_slot([]) == (0, 0)
    items = [_item(0)]
    assert next_slot(items) == (140, 0)  # right of the bounding box, 40 px gap
    for _ in range(3):
        items.append(_item(*next_slot(items)))
    assert [i["x"] for i in items] == [0, 140, 280, 420]
    assert next_slot(items) == (0, 120)  # the fifth starts a new row under the first
    items.append(_item(*next_slot(items)))
    assert next_slot(items) == (140, 120)


async def test_create_then_open_board(ctx: ToolContext, board: str) -> None:
    created = await tools.run_tool(ctx, "create_board", {"title": "Second", "context": "chairs"})
    assert ctx.board_id == created["board_id"] != board
    ctx.board_id = None
    opened = await tools.run_tool(ctx, "open_board", {"board_id": board})
    assert ctx.board_id == board
    assert opened["title"] == "Agent" and opened["items"] == 0
    listed = await tools.run_tool(ctx, "list_boards", {})
    assert {b["id"]: b["items"] for b in listed["boards"]} == {board: 0, created["board_id"]: 0}
    missing = await tools.run_tool(ctx, "open_board", {"board_id": "brd_nope"})
    assert missing["error"] == "BOARD_NOT_FOUND"


@respx.mock
async def test_add_reference_url(ctx: ToolContext, board: str) -> None:
    respx.get("https://shop.test/p").respond(
        200, text='<meta property="og:image" content="https://shop.test/i.png">'
    )
    respx.get("https://shop.test/i.png").respond(200, content=image_bytes())
    with events.subscribe(board) as sub:
        result = await tools.run_tool(ctx, "add_reference", {"url": "https://shop.test/p"})
        seen = []
        while (ev := sub.get(timeout=0.2)) is not None:
            seen.append(ev["type"])
    assert result["deduped"] is False and result["item_ids"] == [result["item_id"]]
    assert "item.added" in seen


async def test_upload_reference_local_file(
    ctx: ToolContext, client: TestClient, board: str, tmp_path: Path
) -> None:
    path = tmp_path / "chair.png"
    path.write_bytes(image_bytes())
    result = await tools.run_tool(
        ctx, "upload_reference", {"path": str(path), "page_url": "https://shop.test/chair"}
    )
    assert "error" not in result, result
    items = client.get(f"/api/boards/{board}/items").json()["items"]
    assert [(i["id"], i["page_url"]) for i in items] == [
        (result["item_id"], "https://shop.test/chair")
    ]


async def test_upload_reference_step_keeps_only_the_file_name(
    ctx: ToolContext, tmp_path: Path
) -> None:
    from app.api.deps import new_session
    from app.db.repos import agent as agent_repo

    run = await tools.run_tool(ctx, "set_goal", {"goal": "g", "deliverables": ["a"]})
    path = tmp_path / "private" / "chair.png"
    path.parent.mkdir()
    path.write_bytes(image_bytes())
    result = await tools.run_tool(ctx, "upload_reference", {"path": str(path), "x": 1, "y": 2})
    assert "error" not in result, result
    with new_session() as s:
        step = agent_repo.steps(s, run["run_id"])[-1]
        assert step.tool == "upload_reference"
        assert step.args_json == {"path": "chair.png", "x": 1, "y": 2}


async def test_upload_reference_rejects_non_image(ctx: ToolContext, tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("not an image")
    result = await tools.run_tool(ctx, "upload_reference", {"path": str(path)})
    assert result["error"] == "UNSUPPORTED_MEDIA_TYPE"
    result = await tools.run_tool(ctx, "upload_reference", {"path": str(tmp_path / "none.png")})
    assert result["error"] == "FILE_NOT_FOUND"


async def test_add_and_visualize_note(ctx: ToolContext, client: TestClient, board: str) -> None:
    first = await tools.run_tool(ctx, "add_note", {"text": "a honey jar"})
    second = await tools.run_tool(ctx, "add_note", {"text": "a tea tin"})
    items = {i["id"]: i for i in client.get(f"/api/boards/{board}/items").json()["items"]}
    assert items[first["item_id"]]["x"] < items[second["item_id"]]["x"]
    queued = await tools.run_tool(ctx, "visualize_note", {"note_id": first["item_id"]})
    assert queued["queued"] is True
    moved = await tools.run_tool(ctx, "move_item", {"item_id": first["item_id"], "x": 5, "y": 6})
    assert (moved["x"], moved["y"]) == (5, 6)
    gone = await tools.run_tool(ctx, "remove_item", {"item_id": second["item_id"]})
    assert gone == {"removed": second["item_id"]}
    assert second["item_id"] not in {
        i["id"] for i in client.get(f"/api/boards/{board}/items").json()["items"]
    }


async def test_item_not_on_board(ctx: ToolContext, client: TestClient, board: str) -> None:
    other = client.post("/api/boards", json={"title": "Other"}).json()["id"]
    note = client.post(
        f"/api/boards/{other}/notes", json={"text": "elsewhere", "x": 0, "y": 0}
    ).json()["id"]
    for name, args in (
        ("visualize_note", {"note_id": note}),
        ("move_item", {"item_id": note, "x": 1, "y": 1}),
        ("remove_item", {"item_id": note}),
    ):
        result = await tools.run_tool(ctx, name, args)
        assert result["error"] == "ITEM_NOT_ON_BOARD", name
    assert client.get(f"/api/boards/{other}/items").json()["items"][0]["id"] == note


async def test_read_board_shape(ctx: ToolContext) -> None:
    for i in range(3):
        await tools.run_tool(ctx, "add_note", {"text": f"note {i}"})
    result = await tools.run_tool(ctx, "read_board", {})
    assert result["board"]["title"] == "Agent"
    assert set(result) == {"board", "items", "profile", "context"}
    assert len(result["items"]) == 3
    first = result["items"][0]
    assert {"id", "kind", "role", "x", "y", "w", "h", "parse_status", "note_text"} <= set(first)
    assert first["note_text"] == "note 2"  # newest first


async def test_lens_tools_pass_refusals_on(ctx: ToolContext) -> None:
    # proposing and confirming a lens is covered by test_lens_service; the tools are thin
    proposed = await tools.run_tool(ctx, "propose_lens", {})
    assert proposed["error"] == "LENS_NOT_ENOUGH_ITEMS"
    chosen = await tools.run_tool(ctx, "set_lens", {"lens_id": "lns_nope"})
    assert chosen["error"] == "LENS_NOT_FOUND"


async def test_locked_demo_refuses_writes(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)
    result = await tools.run_tool(ctx, "add_note", {"text": "blocked"})
    assert result["error"] == "DEMO_LOCKED"
    assert "read-only demo" in result["message"]
