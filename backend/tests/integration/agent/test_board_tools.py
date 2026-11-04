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
    assert set(result) == {"board", "items", "item_counts", "profile", "context"}
    assert len(result["items"]) == 3
    first = result["items"][0]
    assert {"id", "kind", "origin", "role", "x", "y", "w", "h", "parse_status", "note_text"} <= set(
        first
    )
    assert first["note_text"] == "note 2"  # newest first
    assert result["item_counts"] == {"total": 3, "shown": 3, "by_origin": {"note": 3}}


async def test_read_board_tells_originals_from_generated(ctx: ToolContext, board: str) -> None:
    from app.api import deps
    from app.db.repos import items as items_repo

    with deps.new_session() as s:
        original = items_repo.create(
            s, board_id=board, kind="image", origin="upload", sha256="a" * 64,
            original_filename="lancia.jpg", parse_status="completed", x=0, y=0, w=320, h=240,
        )  # fmt: skip
        made = items_repo.create(
            s, board_id=board, kind="image", origin="generated", sha256="b" * 64,
            original_filename="lancia, from the side.png", parse_status="completed",
            parent_item_id=original.id, x=400, y=0, w=320, h=240,
        )  # fmt: skip
        put = items_repo.create(
            s, board_id=board, kind="image", origin="generated", sha256="c" * 64,
            page_title="A wheel " + "very long " * 30, parse_status="completed",
            parent_item_id=original.id, put_source_item_id=made.id, x=800, y=0, w=320, h=240,
        )  # fmt: skip
        s.commit()
        ids = original.id, made.id, put.id
    result = await tools.run_tool(ctx, "read_board", {})
    by_id = {i["id"]: i for i in result["items"]}
    assert by_id[ids[0]]["origin"] == "upload" and by_id[ids[0]]["title"] == "lancia.jpg"
    assert "parent_item_id" not in by_id[ids[0]]  # only links that are set
    assert by_id[ids[1]]["origin"] == "generated" and by_id[ids[1]]["parent_item_id"] == ids[0]
    assert by_id[ids[2]]["put_source_item_id"] == ids[1]
    assert by_id[ids[2]]["title"].startswith("A wheel") and len(by_id[ids[2]]["title"]) <= 80
    assert result["item_counts"]["by_origin"] == {"upload": 1, "generated": 2}


async def test_read_board_caps_items(ctx: ToolContext, board: str) -> None:
    from app.agent.tools import read_board
    from app.api import deps
    from app.db.repos import items as items_repo

    with deps.new_session() as s:
        for i in range(read_board.ITEM_CAP + 5):
            items_repo.create(
                s, board_id=board, kind="note", origin="note", note_text=f"n{i}",
                x=i * 10, y=0, w=100, h=80,
            )  # fmt: skip
        s.commit()
    result = await tools.run_tool(ctx, "read_board", {})
    assert read_board.ITEM_CAP == 60 and len(result["items"]) == 60
    assert result["item_counts"] == {"total": 65, "shown": 60, "by_origin": {"note": 65}}


async def test_lens_tools_pass_refusals_on(ctx: ToolContext) -> None:
    # proposing and confirming a lens is covered by test_lens_service; the tools are thin
    proposed = await tools.run_tool(ctx, "propose_lens", {})
    assert proposed["error"] == "LENS_NOT_ENOUGH_ITEMS"
    chosen = await tools.run_tool(ctx, "set_lens", {"lens_id": "lns_nope"})
    assert chosen["error"] == "LENS_NOT_FOUND"


async def test_set_lens_confirms_a_proposal_over_the_curated_lens(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    # the board already uses its domain's curated lens; a later proposal must still be confirmable
    from app.api import deps
    from app.db.repos import lenses as lenses_repo
    from app.lens_service import curated_lens

    spec = curated_lens("interior")
    assert spec is not None
    assert (
        client.put(f"/api/boards/{board}/lens", json=spec.model_dump(mode="json")).status_code
        == 200
    )
    with deps._factory()() as s:
        proposed = lenses_repo.save(s, board, "interior", "proposed", spec.model_dump(mode="json"))
        s.commit()
        proposed_id = proposed.id

    chosen = await tools.run_tool(ctx, "set_lens", {"lens_id": proposed_id})
    assert chosen["lens"]["status"] == "confirmed"
    lens = client.get(f"/api/boards/{board}/lens").json()["lens"]
    assert lens["id"] == chosen["lens"]["id"]
    assert lens["spec"]["attributes"] == spec.model_dump(mode="json")["attributes"]


async def test_set_lens_refuses_another_boards_lens(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    from app.api import deps
    from app.db.repos import lenses as lenses_repo
    from app.lens_service import curated_lens

    spec = curated_lens("interior")
    assert spec is not None
    other = client.post("/api/boards", json={"title": "Other"}).json()["id"]
    with deps._factory()() as s:
        theirs = lenses_repo.save(s, other, "interior", "proposed", spec.model_dump(mode="json"))
        s.commit()
        theirs_id = theirs.id

    chosen = await tools.run_tool(ctx, "set_lens", {"lens_id": theirs_id})
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
