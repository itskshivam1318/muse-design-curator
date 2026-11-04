"""Long fal jobs: one cap slot and one submit per run, refunds on failure, resume after restart."""

import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import demo, jobs
from app.config import Settings, get_settings
from app.db.models import PluginRun
from app.errors import AppError
from app.explore.visualize import _iso
from app.plugins import longjob, runners, service
from app.plugins.registry import Plugin, get_registry
from app.plugins.runners import BoardCtx, JobCtx, PluginError, RunInput
from app.providers import get_fal
from app.providers.fal import MockFal
from tests.integration.api.test_nodes_api import add_plugin, make_node, upload_image

ENDPOINT = "fal-ai/hunyuan3d/v2/mini/turbo"
RESULT = {"model_mesh": {"url": "https://v3.fal.media/m.glb"}, "seed": 1}


class Crash(BaseException):
    """The process dying mid-poll (not an error the run's code would catch)."""


@pytest.fixture(autouse=True)
def fal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "k")  # mesh requires it
    monkeypatch.setenv("FAL_POLL_S", "0")


@pytest.fixture
def fal() -> MockFal:
    """The process's shared mock (FAL_PROVIDER=mock), scripted."""
    mock = get_fal(get_settings())
    assert isinstance(mock, MockFal)
    mock.statuses = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]
    mock.results[ENDPOINT] = RESULT
    return mock


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    from app.api import deps

    s = deps._factory()()
    yield s
    s.close()


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "Chairs"}).json()["id"]  # type: ignore[no-any-return]


@pytest.fixture
def mesh_handler(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A stand-in mesh.from_image handler (Task 8 writes the real one) that runs a fal job."""
    results: list[dict[str, Any]] = []

    def handler(
        p: Plugin, inputs: list[RunInput], params: dict[str, Any], board: BoardCtx,
        settings: Settings, progress: Callable[[str], None], job: JobCtx | None,
    ) -> dict[str, Any]:  # fmt: skip
        assert job is not None
        run = job.session.get(PluginRun, job.run_id)
        assert run is not None
        payload = lambda _hb: {"input_image_url": "https://f.test/in.png"}
        results.append(longjob.run_fal(job.session, run, ENDPOINT, payload, "mesh", progress))
        return {}

    monkeypatch.setitem(runners.MODEL_HANDLERS, "mesh.from_image", handler)
    return results


def slots(board: str, cap: str = "mesh") -> int:
    return len(demo.windows._hits.get(f"{cap}:{board}", ()))


def fresh(db: Session, run_id: str) -> PluginRun:
    db.expire_all()
    run = db.get(PluginRun, run_id)
    assert run is not None
    return run


@pytest.fixture
def run_id(client: TestClient, board: str) -> str:
    """A queued mesh run (its job not started)."""
    add_plugin(client, board, "mesh")
    node = make_node(client, board, "mesh", [upload_image(client, board)])
    mp = pytest.MonkeyPatch()
    mp.setattr(jobs, "enqueue", lambda *_a, **_k: None)
    try:
        rid = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    finally:
        mp.undo()
    return rid  # type: ignore[no-any-return]


def test_run_fal_happy_path_charges_once(
    db: Session, board: str, run_id: str, fal: MockFal
) -> None:
    seen: list[str] = []
    out = longjob.run_fal(db, fresh(db, run_id), ENDPOINT, {"input_image_url": "u"}, "mesh",
                          seen.append)  # fmt: skip
    assert out == RESULT
    assert fal.count("submit") == 1 and fal.count("status") == 3 and fal.count("result") == 1
    assert slots(board) == 1
    ext = fresh(db, run_id).external_json
    assert ext["endpoint"] == ENDPOINT and ext["cap"] == "mesh" and ext["status"] == "COMPLETED"
    assert ext["request_id"].startswith("mock-") and ext["submitted_at"]
    assert "Waiting in the model's queue" in seen and "The model is working" in seen


def test_run_fal_failed_refunds(db: Session, board: str, run_id: str, fal: MockFal) -> None:
    fal.statuses = ["IN_PROGRESS", "FAILED"]
    with pytest.raises(PluginError) as e:
        longjob.run_fal(db, fresh(db, run_id), ENDPOINT, {}, "mesh", lambda _m: None)
    assert e.value.code == "PLUGIN_MODEL_FAILED"
    assert slots(board) == 0 and fal.count("submit") == 1


def test_run_fal_timeout_refunds(
    db: Session, board: str, run_id: str, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAL_TIMEOUT_S", "0")
    fal.statuses = ["IN_PROGRESS"]
    with pytest.raises(PluginError) as e:
        longjob.run_fal(db, fresh(db, run_id), ENDPOINT, {}, "mesh", lambda _m: None)
    assert e.value.code == "PLUGIN_MODEL_FAILED" and "longer than 0 s" in e.value.message
    assert slots(board) == 0 and fal.count("status") == 1  # asked once, then gave up


def test_run_fal_submit_error_refunds(db: Session, board: str, run_id: str, fal: MockFal) -> None:
    from app.providers.reliability import ModelError

    fal.submit_error = ModelError("MODEL_UNAVAILABLE")
    with pytest.raises(PluginError) as e:
        longjob.run_fal(db, fresh(db, run_id), ENDPOINT, {}, "mesh", lambda _m: None)
    assert e.value.code == "PLUGIN_MODEL_FAILED"
    assert slots(board) == 0 and fresh(db, run_id).external_json is None


def test_cap_reached_no_submit(
    client: TestClient, db: Session, board: str, fal: MockFal,
    mesh_handler: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    monkeypatch.setenv("MESH_PER_BOARD_PER_DAY", "0")
    with pytest.raises(AppError):  # the cap itself, called directly
        longjob.run_fal(db, PluginRun(board_id=board), ENDPOINT, {}, "mesh", lambda _m: None)
    add_plugin(client, board, "mesh")
    node = make_node(client, board, "mesh", [upload_image(client, board)])
    r = client.post(f"/api/nodes/{node['id']}/run")  # JOBS_SYNC: runs inline
    run = fresh(db, r.json()["id"])
    assert (run.status, run.error_code) == ("failed", "DAILY_LIMIT")
    assert fal.count("submit") == 0 and fal.count("upload") == 0 and slots(board) == 0


def test_restart_resumes_without_resubmit(
    db: Session, board: str, run_id: str, fal: MockFal, mesh_handler: list[dict[str, Any]]
) -> None:
    def die(_e: str, _r: str) -> str:
        raise Crash

    fal.status = die  # type: ignore[method-assign]
    with pytest.raises(Crash):
        service.execute_run(db, run_id)
    db.rollback()
    run = fresh(db, run_id)
    assert run.status == "running" and run.external_json["request_id"]
    assert fal.count("submit") == 1 and slots(board) == 1

    del fal.status  # back to the scripted statuses: the job finished while the server was down
    fal.statuses = ["COMPLETED"]
    assert service.recover_stuck_runs(db) == 1
    db.commit()  # the resume job runs after the commit (inline under JOBS_SYNC)
    run = fresh(db, run_id)
    assert run.status == "done", (run.error_code, run.error_message)
    assert fal.count("submit") == 1 and slots(board) == 1
    assert mesh_handler == [RESULT]


def test_recover_without_request_id_still_interrupts(db: Session, run_id: str) -> None:
    run = fresh(db, run_id)
    run.status = "running"
    db.commit()
    assert service.recover_stuck_runs(db) == 1
    db.commit()
    run = fresh(db, run_id)
    assert (run.status, run.error_code) == ("failed", "PLUGIN_INTERRUPTED")


def test_resume_polls_stored_request(db: Session, board: str, run_id: str, fal: MockFal) -> None:
    run = fresh(db, run_id)
    run.external_json = {"endpoint": ENDPOINT, "request_id": "req-9", "status": "IN_PROGRESS",
                         "cap": "mesh", "submitted_at": _iso(datetime.now(UTC))}  # fmt: skip
    db.commit()
    assert longjob.resume(db, fresh(db, run_id)) == RESULT
    assert fal.count("submit") == 0 and slots(board) == 0
    assert all(args[1] == "req-9" for m, args in fal.calls if m in ("status", "result"))


def test_exception_after_submit_refunds(db: Session, board: str, run_id: str, fal: MockFal) -> None:
    def progress(message: str) -> None:
        if message == "The model is working":
            raise RuntimeError("database is locked")  # e.g. the heartbeat's commit failing

    with pytest.raises(RuntimeError):
        longjob.run_fal(db, fresh(db, run_id), ENDPOINT, {}, "mesh", progress)
    assert fal.count("submit") == 1 and slots(board) == 0


def test_payload_builder_heartbeats_keep_the_claim(
    client: TestClient, db: Session, board: str, run_id: str, fal: MockFal
) -> None:
    run = fresh(db, run_id)
    node_id = run.node_id
    stale = _iso(datetime.now(UTC) - timedelta(seconds=service.claim_ttl_s() + 60))
    progress = partial(service._progress, db, run_id, board, node_id)

    def rerun_status() -> int:
        return client.post(f"/api/nodes/{node_id}/run").status_code

    def build(hb: longjob.Progress) -> dict[str, Any]:
        # run_fal heartbeat before building: a claim gone stale beforehand is fresh again
        assert rerun_status() == 409
        fresh(db, run_id).claimed_at = stale  # the first upload outlived the TTL
        db.commit()
        hb("Uploading 2 of 2")
        assert rerun_status() == 409  # not reclaimed by a second run
        return {"input_image_url": "u"}

    run.claimed_at = stale
    db.commit()
    assert longjob.run_fal(db, fresh(db, run_id), ENDPOINT, build, "mesh", progress) == RESULT
    assert fal.count("submit") == 1 and fresh(db, run_id).error_code is None


def test_fal_runs_go_on_the_long_queue(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = get_registry()
    assert service._job_for(registry["mesh"]) == service.LONG_JOB
    assert service._job_for(registry["video"]) == service.LONG_JOB
    assert service._job_for(registry["palette"]) == service.JOB
    assert service._job_for(registry["image"]) == service.JOB
    assert jobs._queue_of[service.LONG_JOB] == "long"
    assert jobs._queue_of[service.RESUME_JOB] == "long"
    assert jobs._queue_of[service.JOB] == "default"


def test_long_queue_busy_default_jobs_still_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBS_SYNC", "0")
    gate = threading.Event()
    started: list[int] = []
    ran = threading.Event()

    def blocked_poll(n: int) -> None:
        started.append(n)
        gate.wait(5)

    jobs.register("t_long", blocked_poll, queue="long")
    jobs.register("t_default", lambda: ran.set())
    try:
        for n in range(jobs.LONG_WORKERS + 2):
            jobs.enqueue("t_long", n=n)
        jobs.enqueue("t_default")
        assert ran.wait(2), "a default job must run while the long queue is full"
        assert len(started) <= jobs.LONG_WORKERS
    finally:
        gate.set()
