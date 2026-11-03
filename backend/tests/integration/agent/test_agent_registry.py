import json
import types
from typing import Any

import pytest

from app import events
from app.agent import tools
from app.agent.context import ToolContext, api_error
from app.api.deps import new_session
from app.db.models import AgentStep
from app.db.repos import agent as agent_repo


def _fake_tool(name: str, run: Any, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(f"fake_{name}")
    module.DEFINITION = {  # type: ignore[attr-defined]
        "name": name,
        "description": "A fake tool.",
        "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}},
    }
    module.run = run  # type: ignore[attr-defined]
    for k, v in attrs.items():
        setattr(module, k, v)
    return module


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Registers `fake_read` (reads the board over the API) and returns the args it saw."""
    seen: list[dict[str, Any]] = []

    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        seen.append(args)
        status, body = await ctx.api.get(f"/api/boards/{ctx.board_id}")
        if status != 200:
            return api_error(status, body)
        return {"title": body["title"], "item_ids": ["item_1"]}

    monkeypatch.setitem(tools.TOOLS, "fake_read", _fake_tool("fake_read", run))
    return seen


def _open_run(board_id: str) -> str:
    with new_session() as s:
        run = agent_repo.create_run(s, board_id, "mcp", "Find chairs", ["note"])
        s.commit()
        return run.id


def _steps(run_id: str) -> list[AgentStep]:
    with new_session() as s:
        return agent_repo.steps(s, run_id)


def _agent_events(sub: events.Subscription) -> list[dict[str, Any]]:
    out = []
    while (ev := sub.get(timeout=0.2)) is not None:
        if ev["type"] == "agent.step":
            out.append(ev)
    return out


async def test_run_tool_records_step_and_publishes(
    ctx: ToolContext, board: str, fake: list[dict[str, Any]]
) -> None:
    ctx.run_id = _open_run(board)
    with events.subscribe(board) as sub:
        result = await tools.run_tool(
            ctx, "fake_read", {"n": 1, "say": "Reading the board.", "highlight": True}
        )
        published = _agent_events(sub)

    assert result == {"title": "Agent", "item_ids": ["item_1"]}
    assert fake == [{"n": 1}]  # say/highlight are stripped before the tool sees its args
    assert len(published) == 1
    data = published[0]["data"]
    assert data["tool"] == "fake_read"
    assert data["say"] == "Reading the board."
    assert data["ok"] is True
    assert data["highlight"] is True
    assert data["item_ids"] == ["item_1"]
    assert data["args"] == {"n": 1}
    [step] = _steps(ctx.run_id)
    assert step.id == data["id"] and step.turn == 1 and step.board_id == board


async def test_refusal_is_recorded_not_raised(
    ctx: ToolContext, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        status, body = await ctx.api.get("/api/boards/board_missing")
        return api_error(status, body)

    monkeypatch.setitem(tools.TOOLS, "fake_refuse", _fake_tool("fake_refuse", run))
    ctx.run_id = _open_run(board)
    result = await tools.run_tool(ctx, "fake_refuse", {})

    assert result["error"] == "BOARD_NOT_FOUND"
    assert result["message"]
    [step] = _steps(ctx.run_id)
    assert step.ok is False
    assert step.result_json == result


async def test_exception_becomes_tool_failed(
    ctx: ToolContext, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setitem(tools.TOOLS, "fake_boom", _fake_tool("fake_boom", run))
    ctx.run_id = _open_run(board)
    result = await tools.run_tool(ctx, "fake_boom", {})

    assert result == {"error": "TOOL_FAILED", "message": "boom"}
    [step] = _steps(ctx.run_id)
    assert step.ok is False and step.tool == "fake_boom"


async def test_unknown_tool(ctx: ToolContext) -> None:
    result = await tools.run_tool(ctx, "no_such_tool", {})
    assert result["error"] == "UNKNOWN_TOOL"


async def test_no_board_open(ctx: ToolContext, fake: list[dict[str, Any]]) -> None:
    ctx.board_id = None
    result = await tools.run_tool(ctx, "fake_read", {})
    assert result["error"] == "NO_BOARD_OPEN"
    assert fake == []


async def test_tool_without_board_runs_when_none_is_open(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"boards": []}

    tool = _fake_tool("fake_list", run, NEEDS_BOARD=False)
    monkeypatch.setitem(tools.TOOLS, "fake_list", tool)
    ctx.board_id = None
    assert await tools.run_tool(ctx, "fake_list", {}) == {"boards": []}


async def test_no_step_without_open_run(
    ctx: ToolContext, board: str, fake: list[dict[str, Any]]
) -> None:
    with events.subscribe(board) as sub:
        result = await tools.run_tool(ctx, "fake_read", {"say": "hi"})
        published = _agent_events(sub)
    assert result["title"] == "Agent"
    assert published == []
    with new_session() as s:
        assert s.query(AgentStep).count() == 0


async def test_say_trimmed_to_200(ctx: ToolContext, board: str, fake: list[dict[str, Any]]) -> None:
    ctx.run_id = _open_run(board)
    await tools.run_tool(ctx, "fake_read", {"say": "  " + "x" * 300 + "  "})
    [step] = _steps(ctx.run_id)
    assert step.say == "x" * 200


async def test_step_is_recorded_on_a_run_the_tool_opens(
    ctx: ToolContext, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        assert ctx.board_id is not None
        ctx.run_id = _open_run(ctx.board_id)
        return {"ok": True}

    monkeypatch.setitem(tools.TOOLS, "fake_goal", _fake_tool("fake_goal", run))
    await tools.run_tool(ctx, "fake_goal", {})
    assert ctx.run_id is not None
    [step] = _steps(ctx.run_id)
    assert step.tool == "fake_goal"


async def test_large_result_is_summarised_on_the_step(
    ctx: ToolContext, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = {"items": [{"id": f"item_{i}", "title": "chair " * 20} for i in range(100)], "n": 100}

    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return big

    monkeypatch.setitem(tools.TOOLS, "fake_big", _fake_tool("fake_big", run))
    ctx.run_id = _open_run(board)
    assert await tools.run_tool(ctx, "fake_big", {}) == big  # the caller gets it all
    [step] = _steps(ctx.run_id)
    assert len(json.dumps(step.result_json).encode()) <= 4096
    assert step.result_json["n"] == 100
    assert step.result_json["truncated"] is True


def test_definitions_add_say_and_highlight(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {}

    monkeypatch.setitem(tools.TOOLS, "fake_a", _fake_tool("fake_a", run))
    monkeypatch.setitem(tools.TOOLS, "fake_mcp", _fake_tool("fake_mcp", run, MCP_ONLY=True))

    by_name = {d["name"]: d for d in tools.definitions("mcp")}
    props = by_name["fake_a"]["parameters"]["properties"]
    assert set(props) == {"n", "say", "highlight"}
    assert "fake_mcp" in by_name
    assert "say" not in tools.TOOLS["fake_a"].DEFINITION["parameters"]["properties"]

    muse = {d["name"] for d in tools.definitions("muse")}
    assert "fake_a" in muse and "fake_mcp" not in muse


def test_api_error_maps_the_app_error_shape() -> None:
    body = {"error": {"code": "DEMO_LOCKED", "message": "Locked", "details": {"x": 1}}}
    assert api_error(403, body) == {"error": "DEMO_LOCKED", "message": "Locked"}
    assert api_error(502, "Bad gateway")["error"] == "HTTP_502"
