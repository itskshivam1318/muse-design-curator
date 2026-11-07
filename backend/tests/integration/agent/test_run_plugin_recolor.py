"""The agent's run_plugin tool drives the python recolor plugin: four options, no model calls."""

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent import tools
from app.agent.context import ApiClient, ToolContext
from app.agent.tools import wait
from app.analysis import locate as locate_mod
from tests.integration.plugins.test_recolor_plugin import BandSeg, shoe


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait, "POLL_S", 0.05)


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    from app.api import deps

    s = deps._factory()()
    yield s
    s.close()


@pytest.fixture
async def ctx(client: TestClient, board: str) -> AsyncIterator[ToolContext]:
    api = ApiClient()
    yield ToolContext(api=api, board_id=board, run_id=None, source="mcp")
    await api.aclose()


async def test_run_plugin_recolor_returns_four_options(
    ctx: ToolContext,
    client: TestClient,
    board: str,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seg = BandSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    item = shoe(client, board, db, ("upper", "midsole", "outsole"))
    params: dict[str, Any] = {
        "mode": "auto",
        "palette": {"name": "Coral Bay", "colors": ["#f6a04d", "#2a9d8f", "#264653", "#e76f51"]},
        "seed": 3,
        "count": 4,
    }
    started = await tools.run_tool(
        ctx, "run_plugin", {"plugin_id": "recolor", "input_item_ids": [item], "params": params}
    )
    assert "error" not in started, started
    done = await tools.run_tool(
        ctx, "wait", {"kind": "plugin_run", "id": started["run_id"], "timeout_s": 30}
    )
    assert done["state"] == "done" and done["timed_out"] is False, done
    out = done["result"]["output"]
    assert len(out["created_item_ids"]) == 4
    assert out["option_item_ids"] == out["created_item_ids"]
