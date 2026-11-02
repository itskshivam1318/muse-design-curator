"""Per-board daily limits as the API reports them."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.test_explore import explore, source
from tests.integration.api.test_visualize import first_option, run

MESSAGE = "Daily limit reached for this board, try tomorrow."


def test_explore_stops_at_the_daily_analyse_limit(
    client: TestClient, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYSE_PER_BOARD_PER_DAY", "1")
    assert explore(client, source(world)).status_code == 200
    r = explore(client, source(world))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "DAILY_LIMIT"
    assert r.json()["error"]["message"] == MESSAGE


def test_visualize_stops_at_the_daily_render_limit(
    client: TestClient, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER_PER_BOARD_PER_DAY", "1")
    opt = first_option(client, world)
    assert run(client, opt["id"]).status_code == 202
    r = run(client, opt["id"])
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "DAILY_LIMIT"
    assert r.json()["error"]["message"] == MESSAGE
