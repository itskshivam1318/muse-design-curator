"""PATCH /api/explorations/{id}: a flower hub's offset from its source item; options' undocked flag."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import events
from app.db.session import run_migrations
from tests.integration.api.test_explore import (  # noqa: F401 (demo_on is a fixture)
    _next_explore_event,
    board_list,
    demo_on,
    error,
    explore,
    source,
)
from tests.integration.db.test_migration_0007 import _populate


def test_patch_sets_offset_and_get_returns_it(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    got = explore(client, source(world)).json()
    assert (got["dx"], got["dy"]) == (None, None)
    with events.subscribe(world["watch"]) as sub:
        r = client.patch(f"/api/explorations/{got['id']}", json={"dx": 240.5, "dy": -80})
        assert r.status_code == 200, r.json()
        assert (r.json()["dx"], r.json()["dy"]) == (240.5, -80.0)
        ev = _next_explore_event(sub)
        assert ev["data"]["id"] == got["id"] and ev["data"]["dx"] == 240.5
    listed = board_list(client, world)[0]
    assert (listed["dx"], listed["dy"]) == (240.5, -80.0)
    r = client.patch(f"/api/explorations/{got['id']}", json={"dx": None, "dy": None})
    assert r.status_code == 200 and (r.json()["dx"], r.json()["dy"]) == (None, None)


def test_patch_requires_both_finite(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    got = explore(client, source(world)).json()
    for body in ({"dx": 1}, {}, {"dx": 1, "dy": "inf"}):
        assert client.patch(f"/api/explorations/{got['id']}", json=body).status_code == 400


def test_patch_unknown_exploration_404(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = client.patch("/api/explorations/exp_missing", json={"dx": 1, "dy": 2})
    assert r.status_code == 404 and error(r) == "EXPLORATION_NOT_FOUND"


@pytest.mark.usefixtures("demo_on")
def test_demo_mode_locks_offsets(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = client.patch("/api/explorations/exp_x", json={"dx": 1, "dy": 2})
    assert r.status_code == 403 and error(r) == "DEMO_LOCKED"


def test_undocked_round_trips(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    got = explore(client, source(world)).json()
    first = got["options"][0]
    assert first["undocked"] is False
    r = client.patch(f"/api/options/{first['id']}", json={"undocked": True})
    assert r.status_code == 200 and r.json()["undocked"] is True
    assert board_list(client, world)[0]["options"][0]["undocked"] is True
    r = client.patch(f"/api/options/{first['id']}", json={"undocked": False})
    assert r.status_code == 200 and r.json()["undocked"] is False


def test_upgrade_0009_on_populated_db(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine, "0008_item_analysis")
    _populate(engine)
    run_migrations(engine)
    with engine.begin() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "0009_living_board"
        )
        assert c.execute(text("SELECT dx, dy FROM explorations")).fetchall() == [(None, None)]
        assert c.execute(text("SELECT undocked FROM explore_options")).fetchall() == [(0,)]
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 2
    engine.dispose()
