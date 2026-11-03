from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app.agent.context import ApiClient, ToolContext


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "Agent"}).json()["id"]  # type: ignore[no-any-return]


@pytest.fixture
async def ctx(client: TestClient, board: str) -> AsyncIterator[ToolContext]:
    """A tool context over the `client` fixture's app (its DB override and JOBS_SYNC apply)."""
    api = ApiClient()
    yield ToolContext(api=api, board_id=board, run_id=None, source="mcp")
    await api.aclose()
