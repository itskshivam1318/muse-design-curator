import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import events
from app.agent import checks, run_state, tools
from app.agent.context import ApiClient, ToolContext
from app.agent.tools import compose_output, read_board
from app.api.deps import new_session
from app.db.models import AgentRun, BoardItem
from app.db.repos import agent as agent_repo
from app.providers.reliability import ModelError
from tests.media import image_bytes


def _image(client: TestClient, board: str, seed: int, x: float = 0, y: float = 0) -> str:
    res = client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", (f"{seed}.png", image_bytes(seed=seed), "image/png"))],
        data={"x": str(x), "y": str(y)},
    )
    return res.json()["results"][0]["item"]["id"]  # type: ignore[no-any-return]


def _items(client: TestClient, board: str) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in client.get(f"/api/boards/{board}/items").json()["items"]}


def _run(run_id: str) -> AgentRun:
    with new_session() as s:
        run = s.get(AgentRun, run_id)
        assert run is not None
        s.expunge(run)
        return run


def _set_check(item_id: str, check: dict[str, Any]) -> None:
    with new_session() as s:
        item = s.get(BoardItem, item_id)
        assert item is not None
        item.check_json = check
        s.commit()


def _drain(sub: Any) -> list[dict[str, Any]]:
    seen = []
    while (ev := sub.get(timeout=0.2)) is not None:
        seen.append(ev)
    return seen


async def _goal(ctx: ToolContext, *deliverables: str) -> str:
    res = await tools.run_tool(
        ctx, "set_goal", {"goal": "a small cabin", "deliverables": list(deliverables)}
    )
    assert "error" not in res, res
    return res["run_id"]  # type: ignore[no-any-return]


def _sections(*pairs: tuple[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {"deliverable": d, "items": [{"item_id": i, "why": f"shows {d}"} for i in ids]}
        for d, ids in pairs
    ]


async def test_set_goal_opens_run_and_publishes(ctx: ToolContext, board: str) -> None:
    with events.subscribe(board) as sub:
        res = await tools.run_tool(
            ctx,
            "set_goal",
            {"goal": "a small cabin", "deliverables": ["front", "side"], "say": "Starting."},
        )
        seen = _drain(sub)
    assert ctx.run_id == res["run_id"]
    run = _run(res["run_id"])
    assert (run.board_id, run.source, run.status) == (board, "mcp", "running")
    assert (run.goal, run.deliverables_json) == ("a small cabin", ["front", "side"])
    runs = [e["data"] for e in seen if e["type"] == "agent.run"]
    assert runs and runs[0]["id"] == run.id and runs[0]["goal"] == "a small cabin"
    with new_session() as s:
        steps = agent_repo.steps(s, run.id)
        assert [(st.turn, st.tool, st.say) for st in steps] == [(1, "set_goal", "Starting.")]


async def test_set_goal_rejects_bad_deliverables(ctx: ToolContext) -> None:
    for bad in ([], ["x" * 81], ["a"] * 13, ["a", "a"], [""]):
        res = await tools.run_tool(ctx, "set_goal", {"goal": "g", "deliverables": bad})
        assert res["error"] == "BAD_DELIVERABLES", bad
    assert (await tools.run_tool(ctx, "set_goal", {"goal": " ", "deliverables": ["a"]}))[
        "error"
    ] == "BAD_GOAL"
    assert ctx.run_id is None


async def test_set_goal_twice_returns_open_run(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    run_id = await _goal(ctx, "front")
    api = ApiClient()
    other = ToolContext(api=api, board_id=board, run_id=None, source="mcp")
    try:
        again = await tools.run_tool(other, "set_goal", {"goal": "else", "deliverables": ["x"]})
    finally:
        await api.aclose()
    assert again["error"] == "RUN_ALREADY_OPEN" and again["run_id"] == run_id
    assert other.run_id == run_id
    assert _run(run_id).goal == "a small cabin"
    with new_session() as s:
        assert len(agent_repo.runs(s, board)) == 1


async def test_compose_output_lays_out_and_stores(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    a = _image(client, board, 1, x=0, y=0)
    b = _image(client, board, 2, x=500, y=100)
    c = _image(client, board, 3, x=1000, y=40)
    _image(client, board, 4, x=1500, y=60)  # stays on the board
    before = _items(client, board)
    rest = [i for i in before.values() if i["id"] not in (a, b, c)]
    right = max(i["x"] + i["w"] for i in rest)
    run_id = await _goal(ctx, "front", "side")
    with events.subscribe(board) as sub:
        res = await tools.run_tool(
            ctx,
            "compose_output",
            {"title": "Cabin", "sections": _sections(("front", [a, b]), ("side", [c]))},
        )
        seen = _drain(sub)
    assert "error" not in res, res
    after = _items(client, board)
    placed = [after[a], after[b], after[c]]
    assert all(i["h"] == compose_output.ITEM_H for i in placed)
    for i in placed:
        src = before[i["id"]]
        assert i["w"] == pytest.approx(src["w"] * compose_output.ITEM_H / src["h"])
    left = right + compose_output.SHEET_GAP
    assert min(i["x"] for i in placed) > left
    assert after[a]["y"] == after[b]["y"] < after[c]["y"]  # one row per section
    assert after[a]["x"] < after[b]["x"]  # items in order

    output = _run(run_id).output_json
    assert output["title"] == "Cabin" and output["sections"] == _sections(
        ("front", [a, b]), ("side", [c])
    )
    notes = [after[n] for n in output["note_ids"]]
    texts = [n["note_text"] for n in notes]
    assert texts[0] == "Cabin" and "front" in texts and "side" in texts
    assert {"shows front", "shows side"} <= set(texts)
    title = notes[0]
    assert (title["x"], title["y"]) == (left, min(i["y"] for i in rest))
    caption_a = next(
        n for n in notes if n["note_text"] == "shows front" and n["x"] == after[a]["x"]
    )
    assert caption_a["y"] > after[a]["y"] + after[a]["h"]
    assert any(e["type"] == "agent.run" and e["data"]["output"] for e in seen)


async def test_compose_output_replaces_previous_sheet(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)
    run_id = await _goal(ctx, "front")
    await tools.run_tool(
        ctx, "compose_output", {"title": "One", "sections": _sections(("front", [a]))}
    )
    first = _run(run_id).output_json["note_ids"]
    res = await tools.run_tool(
        ctx, "compose_output", {"title": "Two", "sections": _sections(("front", [b]))}
    )
    assert "error" not in res, res
    second = _run(run_id).output_json
    live = _items(client, board)
    assert not set(first) & set(live)
    assert set(second["note_ids"]) <= set(live)
    assert second["title"] == "Two" and live[second["note_ids"][0]]["note_text"] == "Two"
    sheet = [live[b]] + [live[n] for n in second["note_ids"]]
    assert not any(_overlap(live[a], s) for s in sheet)  # a, dropped, stays clear of the sheet


def _overlap(p: dict[str, Any], q: dict[str, Any]) -> bool:
    return (
        p["x"] < q["x"] + q["w"]
        and q["x"] < p["x"] + p["w"]
        and p["y"] < q["y"] + q["h"]
        and q["y"] < p["y"] + p["h"]
    )


async def test_compose_output_refusals(ctx: ToolContext, client: TestClient, board: str) -> None:
    a = _image(client, board, 1)
    assert (await tools.run_tool(ctx, "compose_output", {"title": "T", "sections": []}))[
        "error"
    ] == "NO_RUN"
    await _goal(ctx, "front")
    unknown = await tools.run_tool(
        ctx, "compose_output", {"title": "T", "sections": _sections(("back", [a]))}
    )
    assert unknown["error"] == "UNKNOWN_DELIVERABLE"
    stale = await tools.run_tool(
        ctx, "compose_output", {"title": "T", "sections": _sections(("front", ["itm_nope"]))}
    )
    assert stale["error"] == "ITEM_NOT_ON_BOARD"


async def test_finish_done_when_all_delivered(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)
    _set_check(a, {"target": {"answer": "yes"}, "kept": 2, "of": 2, "drifted": [], "unknown": 0})
    run_id = await _goal(ctx, "front", "side")
    await tools.run_tool(
        ctx,
        "compose_output",
        {"title": "Cabin", "sections": _sections(("front", [a]), ("side", [b]))},
    )
    with events.subscribe(board) as sub:
        res = await tools.run_tool(ctx, "finish", {"summary": "Front and side of one cabin."})
        seen = _drain(sub)
    assert res == {"status": "done"}
    run = _run(run_id)
    assert (run.status, run.note, run.finish_refusals) == (
        "done",
        "Front and side of one cabin.",
        0,
    )
    assert any(e["type"] == "agent.run" and e["data"]["status"] == "done" for e in seen)


async def test_finish_refuses_missing_deliverable(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    a = _image(client, board, 1)
    run_id = await _goal(ctx, "front", "exterior side")
    await tools.run_tool(
        ctx, "compose_output", {"title": "T", "sections": _sections(("front", [a]))}
    )
    res = await tools.run_tool(ctx, "finish", {"summary": "done"})
    assert res["error"] == "OUTPUT_NOT_READY"
    assert res["problems"] == ["'exterior side' has no item"]
    run = _run(run_id)
    assert (run.status, run.finish_refusals) == ("running", 1)


async def test_finish_refuses_removed_item(
    ctx: ToolContext, client: TestClient, board: str
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)
    await _goal(ctx, "front")
    await tools.run_tool(
        ctx, "compose_output", {"title": "T", "sections": _sections(("front", [a, b]))}
    )
    assert client.delete(f"/api/items/{b}").status_code == 204  # the person removes it
    res = await tools.run_tool(ctx, "finish", {"summary": "done"})
    assert res["error"] == "OUTPUT_NOT_READY"
    assert res["problems"] == [f"{b} was removed from the board"]


async def test_third_refusal_needs_input(ctx: ToolContext, client: TestClient, board: str) -> None:
    run_id = await _goal(ctx, "front")
    for n in (1, 2):
        res = await tools.run_tool(ctx, "finish", {"summary": "done"})
        assert res["error"] == "OUTPUT_NOT_READY" and _run(run_id).finish_refusals == n
    with events.subscribe(board) as sub:
        res = await tools.run_tool(ctx, "finish", {"summary": "done"})
        seen = _drain(sub)
    assert res["status"] == "needs_input" and res["error"] == "OUTPUT_NOT_READY"
    assert res["problems"] == ["'front' has no item"]
    assert _steps(run_id)[-1].ok is False
    run = _run(run_id)
    assert (run.status, run.finish_refusals) == ("needs_input", 3)
    assert any(e["type"] == "agent.run" and e["data"]["status"] == "needs_input" for e in seen)


async def test_finish_refuses_inconsistent_output(
    ctx: ToolContext, client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)

    class Odd:
        def structured(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> Any:
            assert len(images) == 2 and schema["title"] == "output_consistency"
            return {"one_design": False, "outliers": [1], "reason": "a different roof"}

    monkeypatch.setattr(checks, "get_reasoning", lambda settings: Odd())
    run_id = await _goal(ctx, "front", "side")
    await tools.run_tool(
        ctx,
        "compose_output",
        {"title": "T", "sections": _sections(("front", [a]), ("side", [b]))},
    )
    res = await tools.run_tool(ctx, "finish", {"summary": "done"})
    assert res["error"] == "OUTPUT_NOT_READY"
    assert res["problems"] == [f"{b} does not show the same design as the rest: a different roof"]
    assert _run(run_id).finish_refusals == 1


def _steps(run_id: str) -> list[Any]:
    with new_session() as s:
        found = agent_repo.steps(s, run_id)
        for st in found:
            s.expunge(st)
        return found


async def test_create_board_leaves_the_previous_boards_run(ctx: ToolContext) -> None:
    first_run = await _goal(ctx, "front")
    created = await tools.run_tool(ctx, "create_board", {"title": "Second"})
    assert ctx.board_id == created["board_id"] and ctx.run_id is None
    await tools.run_tool(ctx, "read_board", {})
    assert [st.tool for st in _steps(first_run)] == ["set_goal"]


async def test_step_not_recorded_on_another_boards_run(
    ctx: ToolContext, client: TestClient
) -> None:
    first_run = await _goal(ctx, "front")
    ctx.board_id = client.post("/api/boards", json={"title": "Other"}).json()["id"]
    await tools.run_tool(ctx, "read_board", {})
    assert [st.tool for st in _steps(first_run)] == ["set_goal"]


async def test_set_goal_replace_pauses_the_open_run(ctx: ToolContext) -> None:
    first = await _goal(ctx, "front")
    res = await tools.run_tool(
        ctx, "set_goal", {"goal": "a bigger cabin", "deliverables": ["side"], "replace": True}
    )
    assert "error" not in res, res
    assert res["run_id"] != first and ctx.run_id == res["run_id"]
    assert _run(first).status == "paused"
    new = _run(res["run_id"])
    assert (new.status, new.goal, new.deliverables_json) == ("running", "a bigger cabin", ["side"])


async def test_finish_check_unavailable_keeps_refusals(
    ctx: ToolContext, client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)

    class Down:
        def structured(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> Any:
            raise ModelError("MODEL_TIMEOUT")

    monkeypatch.setattr(checks, "get_reasoning", lambda settings: Down())
    run_id = await _goal(ctx, "front", "side")
    await tools.run_tool(
        ctx,
        "compose_output",
        {"title": "T", "sections": _sections(("front", [a]), ("side", [b]))},
    )
    res = await tools.run_tool(ctx, "finish", {"summary": "done"})
    assert res["error"] == "CHECK_UNAVAILABLE" and "MODEL_TIMEOUT" in res["message"]
    run = _run(run_id)
    assert (run.status, run.finish_refusals) == ("running", 0)


async def test_finish_checks_thumbnails(
    ctx: ToolContext, client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)
    fetched: list[str] = []
    real = ctx.api.get_bytes

    async def spy(path: str) -> bytes | None:
        fetched.append(path)
        return await real(path)

    monkeypatch.setattr(ctx.api, "get_bytes", spy)
    await _goal(ctx, "front", "side")
    await tools.run_tool(
        ctx,
        "compose_output",
        {"title": "T", "sections": _sections(("front", [a]), ("side", [b]))},
    )
    await tools.run_tool(ctx, "finish", {"summary": "done"})
    assert fetched == [f"/api/items/{a}/image?size=thumb", f"/api/items/{b}/image?size=thumb"]


async def test_parallel_steps_get_distinct_turns(ctx: ToolContext) -> None:
    run_id = await _goal(ctx, "front")
    await asyncio.gather(*(tools.run_tool(ctx, "read_board", {}) for _ in range(8)))
    assert sorted(st.turn for st in _steps(run_id)) == list(range(1, 10))


async def test_tool_failure_without_message_names_the_exception(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        raise KeyError()

    monkeypatch.setattr(read_board, "run", boom)
    res = await tools.run_tool(ctx, "read_board", {})
    assert res == {"error": "TOOL_FAILED", "message": "KeyError"}


async def test_a_contrast_section_is_left_out_of_the_one_design_check(
    ctx: ToolContext, client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _image(client, board, 1)
    b = _image(client, board, 2, x=500)
    c = _image(client, board, 3, x=1000)
    compared: list[int] = []

    class Same:
        def structured(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> Any:
            compared.append(len(images))
            return {"one_design": True, "outliers": [], "reason": ""}

    monkeypatch.setattr(checks, "get_reasoning", lambda settings: Same())
    run_id = await _goal(ctx, "front", "side", "not this")
    sections = _sections(("front", [a]), ("side", [b]), ("not this", [c]))
    sections[2]["contrast"] = True
    res = await tools.run_tool(ctx, "compose_output", {"title": "T", "sections": sections})
    assert "error" not in res, res
    assert _run(run_id).output_json["sections"][2]["contrast"] is True
    res = await tools.run_tool(ctx, "finish", {"summary": "done"})
    assert res == {"status": "done"}
    assert compared == [2]  # the counter-example is on the sheet but not compared


async def test_set_goal_refused_while_chat_open(ctx: ToolContext, board: str) -> None:
    chat, created = await run_state.start(board, "muse", "g", [])
    assert created
    res = await tools.run_tool(ctx, "set_goal", {"goal": "g2", "deliverables": ["a"]})
    assert res["error"] == "CHAT_OPEN"
    assert ctx.run_id is None
    assert _run(chat["id"]).status == "running"


async def test_set_goal_replace_ends_chat_run(ctx: ToolContext, board: str) -> None:
    chat, _ = await run_state.start(board, "muse", "g", [])
    res = await tools.run_tool(
        ctx, "set_goal", {"goal": "g2", "deliverables": ["a"], "replace": True}
    )
    assert "error" not in res, res
    assert _run(chat["id"]).status == "done"
    assert _run(res["run_id"]).source == "mcp"


async def test_chat_start_refused_while_mcp_run_open(ctx: ToolContext, board: str) -> None:
    await _goal(ctx, "a")
    res, created = await run_state.start(board, "muse", "g", [])
    assert not created and res["error"] == "MCP_RUN_OPEN"


async def test_current_does_not_fall_back_across_sources(ctx: ToolContext, board: str) -> None:
    chat, _ = await run_state.start(board, "muse", "g", [])
    assert await run_state.current(board, None, "mcp") is None
    found = await run_state.current(board, None, "muse")
    assert found is not None and found["id"] == chat["id"]
    found = await run_state.current(board, None)
    assert found is not None and found["id"] == chat["id"]
