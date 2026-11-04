"""Long fal jobs: one cap slot and one submit per run, refunds on failure, resume after restart."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import demo, jobs
from app.config import Settings
from app.db.models import PluginRun
from app.errors import AppError
from app.explore.visualize import _iso
from app.plugins import longjob, runners, service
from app.plugins.registry import Plugin
from app.plugins.runners import BoardCtx, JobCtx, PluginError, RunInput
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
def fal(monkeypatch: pytest.MonkeyPatch) -> MockFal:
    mock = MockFal(statuses=["IN_QUEUE", "IN_PROGRESS", "COMPLETED"], results={ENDPOINT: RESULT})
    monkeypatch.setattr(longjob, "get_fal", lambda _s: mock)
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
        payload = lambda: {"input_image_url": "https://f.test/in.png"}
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
