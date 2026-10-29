"""Plugin runs: claims, removed inputs, startup recovery."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import jobs
from app.db.models import ItemAttribute, PluginRun
from app.explore.visualize import _iso
from app.plugins import service
from tests.integration.api.test_nodes_api import (
    add_plugin,
    error,
    make_node,
    upload_image,
)


@pytest.fixture
def no_jobs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append({"name": name, **kw}))
    return queued


def fresh(db: Session, run_id: str) -> PluginRun:
    db.expire_all()
    run = db.get(PluginRun, run_id)
    assert run is not None
    return run


def test_run_conflict_409_and_stale_allowed(
    client: TestClient, board: str, db: Session, no_jobs: list[dict[str, Any]]
) -> None:
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [upload_image(client, board)])
    r = client.post(f"/api/nodes/{node['id']}/run")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    first = r.json()["id"]
    assert [j for j in no_jobs if j["name"] == "plugin_run"] == [
        {"name": "plugin_run", "run_id": first}
    ]
    again = client.post(f"/api/nodes/{node['id']}/run")
    assert again.status_code == 409 and error(again) == "NODE_RUNNING"
    run = fresh(db, first)
    run.claimed_at = _iso(datetime.now(UTC) - timedelta(seconds=121))
    db.commit()
    r = client.post(f"/api/nodes/{node['id']}/run")
    assert r.status_code == 202 and r.json()["id"] != first
    old = fresh(db, first)
    assert (old.status, old.error_code) == ("failed", "PLUGIN_INTERRUPTED")


def test_removed_input_skipped_and_below_min_fails(
    client: TestClient, board: str, db: Session, no_jobs: list[dict[str, Any]]
) -> None:
    add_plugin(client, board, "palette")
    a, b = upload_image(client, board, 1), upload_image(client, board, 2)
    node = make_node(client, board, "palette", [a, b])
    run_id = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    assert client.delete(f"/api/items/{b}").status_code == 204
    service.plugin_run_job(run_id)
    run = fresh(db, run_id)
    assert run.status == "done", run.error_message
    keys = {(r.item_id, r.key) for r in db.query(ItemAttribute).filter_by(key="palette")}
    assert keys == {(a, "palette")}

    run_id = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    assert client.delete(f"/api/items/{a}").status_code == 204
    service.plugin_run_job(run_id)
    run = fresh(db, run_id)
    assert (run.status, run.error_code) == ("failed", "PLUGIN_BAD_INPUT")
    assert run.error_message == "Some inputs were removed"


def test_crash_is_plugin_crashed(
    client: TestClient, board: str, db: Session, no_jobs: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [upload_image(client, board)])
    run_id = client.post(f"/api/nodes/{node['id']}/run").json()["id"]

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("bug")

    monkeypatch.setattr(service, "run_plugin", boom)
    service.plugin_run_job(run_id)
    run = fresh(db, run_id)
    assert (run.status, run.error_code, run.error_message) == (
        "failed", "PLUGIN_CRASHED", "Something went wrong",
    )  # fmt: skip


def test_recover_stuck_runs_marks_interrupted(
    client: TestClient, board: str, db: Session, no_jobs: list[dict[str, Any]]
) -> None:
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [upload_image(client, board)])
    queued = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    running = fresh(db, queued)
    running.status = "running"
    db.commit()
    assert service.recover_stuck_runs(db) == 1
    db.commit()
    run = fresh(db, queued)
    assert (run.status, run.error_code) == ("failed", "PLUGIN_INTERRUPTED")
    assert run.finished_at is not None
    assert service.recover_stuck_runs(db) == 0


def test_progress_refreshes_the_claim(
    client: TestClient, board: str, db: Session, no_jobs: list[dict[str, Any]]
) -> None:
    add_plugin(client, board, "palette")
    node = make_node(client, board, "palette", [upload_image(client, board)])
    run_id = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    old = _iso(datetime.now(UTC) - timedelta(seconds=500))
    run = fresh(db, run_id)
    run.claimed_at = old
    db.commit()
    service._progress(db, run_id, board, node["id"], "Editing image 2 of 4")
    run = fresh(db, run_id)
    assert run.progress_json == {"message": "Editing image 2 of 4"}
    assert run.claimed_at is not None and run.claimed_at > old
    again = client.post(f"/api/nodes/{node['id']}/run")  # a healthy run is not stale
    assert again.status_code == 409 and error(again) == "NODE_RUNNING"
