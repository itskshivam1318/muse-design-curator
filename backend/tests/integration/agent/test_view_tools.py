"""render_view and put_into as agent tools: they wait for the job and hand back the new picture."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent import context
from app.agent.context import ApiClient, ToolContext, require_item
from app.agent.tools import definitions, run_tool, wait
from app.providers.reliability import ModelError
from app.views import service

POINT = [{"point": {"fx": 0.5, "fy": 0.5}}]


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait, "POLL_S", 0.05)


@pytest.fixture
async def ctx(world: dict[str, Any], client: TestClient) -> AsyncIterator[ToolContext]:
    api = ApiClient()
    yield ToolContext(api=api, board_id=world["watch"], run_id=None, source="mcp")
    await api.aclose()


@pytest.fixture
def ids(world: dict[str, Any]) -> tuple[str, str]:
    a, b = world["items"][world["watch"]][:2]
    return a, b


@pytest.fixture
def event_never_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(context, "_await_job", never)


async def test_render_view_tool_returns_item_with_sync_jobs(
    ctx: ToolContext, ids: tuple[str, str]
) -> None:
    res = await run_tool(ctx, "render_view", {"anchor_id": ids[0], "view": "from the rear"})
    assert "error" not in res, res
    assert res["item_ids"] == [res["item_id"]]
    item = await require_item(ctx, res["item_id"])
    assert item["parent_item_id"] == ids[0]


@pytest.mark.file_db
async def test_two_views_each_get_their_own_item(ctx: ToolContext, ids: tuple[str, str]) -> None:
    a, b = await asyncio.gather(
        run_tool(ctx, "render_view", {"anchor_id": ids[0], "view": "from the rear"}),
        run_tool(ctx, "render_view", {"anchor_id": ids[0], "view": "from above"}),
    )
    assert "error" not in a and "error" not in b, (a, b)
    assert a["item_id"] != b["item_id"] and a["job_id"] != b["job_id"]


async def test_render_view_tool_refuses_a_note(ctx: ToolContext) -> None:
    note = await run_tool(ctx, "add_note", {"text": "a thought"})
    assert "error" not in note, note
    note_id = note["item_ids"][0]
    res = await run_tool(ctx, "render_view", {"anchor_id": note_id, "view": "from above"})
    assert res["error"] == "VIEW_NOT_IMAGE"


async def test_render_view_unknown_item_is_not_on_board(ctx: ToolContext) -> None:
    res = await run_tool(ctx, "render_view", {"anchor_id": "nope", "view": "from above"})
    assert res["error"] == "ITEM_NOT_ON_BOARD"


async def test_render_view_failure_comes_back_as_refusal(
    ctx: ToolContext, ids: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing:
        id, model, is_mock = "failing", "failing-image", True

        def edit(self, image: bytes, prompt: str) -> bytes:
            raise ModelError("MODEL_TIMEOUT", message="slow")

    monkeypatch.setattr(service, "get_image_provider", lambda _s: Failing())
    res = await run_tool(ctx, "render_view", {"anchor_id": ids[0], "view": "from the rear"})
    assert res["error"] == "MODEL_TIMEOUT" and res["job_id"].startswith("view_")


async def test_put_into_tool_with_a_point(ctx: ToolContext, ids: tuple[str, str]) -> None:
    target, source = ids
    args = {"target_id": target, "source_id": source, "spots": POINT}
    res = await run_tool(ctx, "put_into", args)
    assert "error" not in res, res
    item = await require_item(ctx, res["item_id"])
    assert item["parent_item_id"] == target and item["put_source_item_id"] == source
    assert res["check"] == item["check"] is not None  # the result comes back with its check


async def test_put_into_tool_unknown_part(ctx: ToolContext, ids: tuple[str, str]) -> None:
    args = {"target_id": ids[0], "source_id": ids[1], "spots": [{"part": "no_such_part"}]}
    res = await run_tool(ctx, "put_into", args)
    assert res["error"] == "PART_NOT_FOUND"


@pytest.mark.usefixtures("event_never_arrives")
async def test_wait_job_finds_the_result_later(ctx: ToolContext, ids: tuple[str, str]) -> None:
    res = await run_tool(ctx, "render_view", {"anchor_id": ids[0], "view": "from the rear"})
    assert res["timed_out"] is True and res["job_id"].startswith("view_")
    done = await run_tool(ctx, "wait", {"kind": "job", "id": res["job_id"], "timeout_s": 1})
    assert done["state"] == "done" and done["item_ids"] == [done["result"]["item_id"]]


@pytest.mark.usefixtures("event_never_arrives")
async def test_wait_job_finds_a_put_result(ctx: ToolContext, ids: tuple[str, str]) -> None:
    args = {"target_id": ids[0], "source_id": ids[1], "spots": POINT}
    res = await run_tool(ctx, "put_into", args)
    assert res["timed_out"] is True and res["job_id"].startswith("put_")
    done = await run_tool(ctx, "wait", {"kind": "job", "id": res["job_id"], "timeout_s": 1})
    assert done["state"] == "done" and done["result"]["item_id"]


@pytest.mark.usefixtures("event_never_arrives")
async def test_wait_job_is_busy_while_the_result_is_checked(
    ctx: ToolContext, ids: tuple[str, str], world: dict[str, Any]
) -> None:
    from app.db.models import BoardItem

    res = await run_tool(ctx, "render_view", {"anchor_id": ids[0], "view": "from the rear"})
    s = world["session"]
    s.expire_all()
    item = next(
        i for i in s.query(BoardItem).filter(BoardItem.parent_item_id == ids[0])
        if (i.generation_json or {}).get("view_job") == res["job_id"]
    )  # fmt: skip
    item.generation_json = {**item.generation_json, "checking": True}
    s.commit()
    busy = await run_tool(ctx, "wait", {"kind": "job", "id": res["job_id"], "timeout_s": 1})
    assert busy["timed_out"] is True and busy["state"] == "checking"


async def test_wait_job_unknown_id_times_out(ctx: ToolContext) -> None:
    res = await run_tool(ctx, "wait", {"kind": "job", "id": "view_nope", "timeout_s": 1})
    assert res["timed_out"] is True


def test_new_tools_are_listed_for_mcp_and_muse() -> None:
    for source in ("mcp", "muse"):
        assert {"render_view", "put_into"} <= {d["name"] for d in definitions(source)}
