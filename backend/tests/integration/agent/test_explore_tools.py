from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent import tools
from app.agent.context import ApiClient, ToolContext
from app.agent.tools import wait
from tests.integration.api.test_explore import source
from tests.media import image_bytes


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait, "POLL_S", 0.05)


@pytest.fixture
async def wctx(world: dict[str, Any], client: TestClient) -> AsyncIterator[ToolContext]:
    """A tool context on the seeded board, where items already carry dimensions to explore."""
    api = ApiClient()
    yield ToolContext(api=api, board_id=world["watch"], run_id=None, source="mcp")
    await api.aclose()


async def test_analyse_then_get_analysis(wctx: ToolContext, world: dict[str, Any]) -> None:
    item = source(world)
    queued = await tools.run_tool(wctx, "analyse", {"item_id": item})
    assert queued["queued"] is True and queued["item_ids"] == [item]
    done = await tools.run_tool(wctx, "wait", {"kind": "analysis", "id": item, "timeout_s": 5})
    assert done["timed_out"] is False and done["state"] in ("completed", "failed")
    analysis = await tools.run_tool(wctx, "get_analysis", {"item_id": item})
    assert "error" not in analysis, analysis
    assert analysis["dimensions"] and "parts" in analysis


async def test_add_dimension_with_value(wctx: ToolContext, world: dict[str, Any]) -> None:
    item = source(world)
    added = await tools.run_tool(
        wctx, "add_dimension", {"item_id": item, "label": "Warmth", "value": "warm"}
    )
    assert "error" not in added, added
    assert added["dimension"]["key"] == "warmth"
    analysis = await tools.run_tool(wctx, "get_analysis", {"item_id": item})
    warmth = next(d for d in analysis["dimensions"] if d["key"] == "warmth")
    assert warmth["value"] == "warm" and warmth["source"] == "you"


async def test_explore_returns_options(wctx: ToolContext, world: dict[str, Any]) -> None:
    result = await tools.run_tool(
        wctx, "explore", {"item_id": source(world), "dimension": "markers"}
    )
    assert "error" not in result, result
    assert result["exploration_id"] and 6 <= len(result["options"]) <= 10
    assert {"id", "name"} <= set(result["options"][0])


async def test_visualize_then_wait_returns_item_and_check(
    wctx: ToolContext, world: dict[str, Any]
) -> None:
    explored = await tools.run_tool(
        wctx, "explore", {"item_id": source(world), "dimension": "markers"}
    )
    option = explored["options"][0]["id"]
    queued = await tools.run_tool(wctx, "visualize_option", {"option_id": option})
    assert queued == {"queued": True, "option_id": option, "item_ids": [source(world)]}
    done = await tools.run_tool(wctx, "wait", {"kind": "option", "id": option, "timeout_s": 5})
    assert done["timed_out"] is False and done["state"] == "visualized"
    assert done["result"]["item_id"] and "check" in done["result"]
    assert done["item_ids"] == [done["result"]["item_id"]]
    again = await tools.run_tool(wctx, "wait", {"kind": "item", "id": done["result"]["item_id"]})
    assert again["state"] == "completed" or again["state"] == "failed"


async def test_keep_option(wctx: ToolContext, world: dict[str, Any]) -> None:
    explored = await tools.run_tool(
        wctx, "explore", {"item_id": source(world), "dimension": "markers"}
    )
    option = explored["options"][0]["id"]
    await tools.run_tool(wctx, "visualize_option", {"option_id": option})
    take = (await tools.run_tool(wctx, "wait", {"kind": "option", "id": option}))["result"]
    kept = await tools.run_tool(
        wctx, "keep_option", {"option_id": option, "item_id": take["item_id"]}
    )
    assert kept["status"] == "kept" and kept["item_ids"] == [take["item_id"]]
    undone = await tools.run_tool(wctx, "unkeep_option", {"option_id": option})
    assert undone["status"] == "visualized"


async def test_option_not_on_board(
    wctx: ToolContext, ctx: ToolContext, world: dict[str, Any]
) -> None:
    explored = await tools.run_tool(
        wctx, "explore", {"item_id": source(world), "dimension": "markers"}
    )
    option = explored["options"][0]["id"]
    for name in ("visualize_option", "unkeep_option"):
        assert (await tools.run_tool(ctx, name, {"option_id": option}))["error"] == (
            "OPTION_NOT_ON_BOARD"
        )
    waited = await tools.run_tool(ctx, "wait", {"kind": "option", "id": option})
    assert waited["error"] == "OPTION_NOT_ON_BOARD"
    foreign = await tools.run_tool(ctx, "analyse", {"item_id": source(world)})
    assert foreign["error"] == "ITEM_NOT_ON_BOARD"


async def test_daily_limit_comes_back_as_its_code(
    wctx: ToolContext, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYSE_PER_BOARD_PER_DAY", "1")
    item = source(world)
    first = await tools.run_tool(wctx, "explore", {"item_id": item, "dimension": "markers"})
    assert "error" not in first
    second = await tools.run_tool(wctx, "explore", {"item_id": item, "dimension": "markers"})
    assert second["error"] == "DAILY_LIMIT"


async def test_wait_times_out(
    ctx: ToolContext, client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = (await tools.run_tool(ctx, "add_note", {"text": "a honey jar"}))["item_id"]
    real_get = ctx.api.get

    async def busy(path: str) -> Any:
        status, body = await real_get(path)
        if path.endswith("/items"):
            for item in body["items"]:
                item["generation"] = {"visualizing_since": "2026-11-03T00:00:00Z"}
        return status, body

    monkeypatch.setattr(ctx.api, "get", busy)
    result = await tools.run_tool(ctx, "wait", {"kind": "note", "id": note, "timeout_s": 1})
    assert result == {"state": "visualizing", "result": None, "timed_out": True}


async def test_wait_note_returns_idle_when_not_visualizing(ctx: ToolContext) -> None:
    note = (await tools.run_tool(ctx, "add_note", {"text": "a honey jar"}))["item_id"]
    result = await tools.run_tool(ctx, "wait", {"kind": "note", "id": note})
    assert result["state"] == "idle" and result["timed_out"] is False
    assert result["result"] == {"note_id": note, "item_id": None, "check": None}
    assert result["item_ids"] == [note]  # nothing made yet: the note itself is the focus


def test_wait_clamps_timeout() -> None:
    assert wait.clamp_timeout(0) == 1
    assert wait.clamp_timeout(-5) == 1
    assert wait.clamp_timeout(9999) == 120
    assert wait.clamp_timeout(30) == 30
    assert wait.clamp_timeout(None) == 60
    assert wait.clamp_timeout("soon") == 60


async def test_wait_rejects_unknown_kind(ctx: ToolContext) -> None:
    result = await tools.run_tool(ctx, "wait", {"kind": "coffee", "id": "x"})
    assert result["error"] == "BAD_KIND"


async def test_run_plugin_colour(ctx: ToolContext, client: TestClient, board: str) -> None:
    r = client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", ("a.png", image_bytes(size=(320, 256)), "image/png"))],
    )
    img = r.json()["results"][0]["item"]["id"]
    started = await tools.run_tool(
        ctx, "run_plugin", {"plugin_id": "palette", "input_item_ids": [img]}
    )
    assert "error" not in started, started
    assert started["item_ids"] == [img]
    done = await tools.run_tool(
        ctx, "wait", {"kind": "plugin_run", "id": started["run_id"], "timeout_s": 5}
    )
    assert done["state"] == "done" and done["timed_out"] is False
    assert done["result"]["id"] == started["run_id"]
    missing = await tools.run_tool(
        ctx, "run_plugin", {"plugin_id": "palette", "input_item_ids": ["item_nope"]}
    )
    assert missing["error"] == "ITEM_NOT_ON_BOARD"


async def test_compose_output_undocks_a_kept_take(
    wctx: ToolContext, world: dict[str, Any], client: TestClient
) -> None:
    """A kept take is drawn in its explore ring unless undocked, so the sheet must undock it."""
    explored = await tools.run_tool(
        wctx, "explore", {"item_id": source(world), "dimension": "markers"}
    )
    option = explored["options"][0]["id"]
    await tools.run_tool(wctx, "visualize_option", {"option_id": option})
    take = (await tools.run_tool(wctx, "wait", {"kind": "option", "id": option}))["result"]
    await tools.run_tool(wctx, "keep_option", {"option_id": option, "item_id": take["item_id"]})
    goal = await tools.run_tool(wctx, "set_goal", {"goal": "a take", "deliverables": ["take"]})
    assert "error" not in goal, goal
    sections = [{"deliverable": "take", "items": [{"item_id": take["item_id"], "why": "it"}]}]
    res = await tools.run_tool(wctx, "compose_output", {"title": "Sheet", "sections": sections})
    assert "error" not in res, res
    explorations = client.get(f"/api/boards/{world['watch']}/explorations").json()["explorations"]
    opt = next(o for e in explorations for o in e["options"] if o["id"] == option)
    assert opt["undocked"] is True and opt["kept_item_id"] == take["item_id"]
