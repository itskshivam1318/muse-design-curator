from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import demo, events
from app.api import deps
from app.db.repos import agent as agent_repo
from tests.integration.api.test_demo import PASSCODE, SECRET, locked


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]  # type: ignore[no-any-return]


def seed(board: str, goal: str = "g", n_steps: int = 0) -> tuple[str, list[str]]:
    with deps._factory()() as s:
        run = agent_repo.create_run(s, board, "mcp", goal, ["board"])
        ids = [agent_repo.add_step(s, run.id, tool=f"t{i}", say=f"s{i}").id for i in range(n_steps)]
        s.commit()
        return run.id, ids


def test_list_runs_newest_first(client: TestClient, board: str) -> None:
    a, _ = seed(board, "first")
    b, _ = seed(board, "second")
    r = client.get(f"/api/boards/{board}/agent-runs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert [x["id"] for x in runs] == [b, a]
    assert set(runs[0]) == {
        "id", "board_id", "source", "status", "goal", "deliverables", "output",
        "finish_refusals", "note", "created_at", "updated_at",
    }  # fmt: skip
    assert client.get("/api/boards/board_nope/agent-runs").status_code == 404


def test_run_with_steps_in_order(client: TestClient, board: str) -> None:
    run_id, step_ids = seed(board, n_steps=3)
    d = client.get(f"/api/agent-runs/{run_id}").json()
    assert d["id"] == run_id
    assert [s["id"] for s in d["steps"]] == step_ids
    assert [s["turn"] for s in d["steps"]] == [1, 2, 3]
    assert set(d["steps"][0]) == {
        "id", "run_id", "turn", "tool", "args", "say", "ok", "result", "item_ids",
        "highlight", "created_at",
    }  # fmt: skip


def test_patch_highlight_publishes(client: TestClient, board: str) -> None:
    run_id, (step_id,) = seed(board, n_steps=1)
    with events.subscribe(board) as sub:
        r = client.patch(f"/api/agent-steps/{step_id}", json={"highlight": True})
        ev = sub.get(timeout=2)
    assert r.status_code == 200 and r.json()["highlight"] is True
    assert ev and ev["type"] == "agent.step"
    assert ev["data"]["id"] == step_id and ev["data"]["highlight"] is True
    assert client.get(f"/api/agent-runs/{run_id}").json()["steps"][0]["highlight"] is True
    off = client.patch(f"/api/agent-steps/{step_id}", json={"highlight": False})
    assert off.json()["highlight"] is False
    assert client.patch(f"/api/agent-steps/{step_id}", json={}).status_code in (400, 422)


def test_patch_highlight_locked_in_demo(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, (step_id,) = seed(board, n_steps=1)
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", PASSCODE)
    monkeypatch.setenv("DEMO_SECRET", SECRET)
    r: Any = client.patch(f"/api/agent-steps/{step_id}", json={"highlight": True})
    assert locked(r)
    assert client.get(f"/api/agent-runs/{run_id}").json()["steps"][0]["highlight"] is False


def test_patch_run_paused_publishes(client: TestClient, board: str) -> None:
    run_id, _ = seed(board)
    with events.subscribe(board) as sub:
        r = client.patch(f"/api/agent-runs/{run_id}", json={"status": "paused"})
        ev = sub.get(timeout=2)
    assert r.status_code == 200 and r.json()["status"] == "paused"
    assert ev and ev["type"] == "agent.run" and ev["data"]["status"] == "paused"
    assert client.get(f"/api/agent-runs/{run_id}").json()["status"] == "paused"
    again = client.patch(f"/api/agent-runs/{run_id}", json={"status": "paused"})
    assert again.status_code == 200 and again.json()["status"] == "paused"
    with deps._factory()() as s:
        done = agent_repo.create_run(s, board, "mcp", "g", ["board"])
        done.status = "done"
        s.commit()
        done_id = done.id
    closed = client.patch(f"/api/agent-runs/{done_id}", json={"status": "paused"})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "RUN_NOT_OPEN"
    for bad in ({"status": "done"}, {"status": "running"}, {}):
        assert client.patch(f"/api/agent-runs/{run_id}", json=bad).status_code in (400, 422)
    missing = client.patch("/api/agent-runs/agent_run_nope", json={"status": "paused"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_patch_run_locked_in_demo(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _ = seed(board)
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", PASSCODE)
    monkeypatch.setenv("DEMO_SECRET", SECRET)
    r: Any = client.patch(f"/api/agent-runs/{run_id}", json={"status": "paused"})
    assert locked(r)
    assert client.get(f"/api/agent-runs/{run_id}").json()["status"] == "running"


def test_unknown_run_404(client: TestClient) -> None:
    r = client.get("/api/agent-runs/agent_run_nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "RUN_NOT_FOUND"
    r = client.patch("/api/agent-steps/agent_step_nope", json={"highlight": True})
    assert r.status_code == 404 and r.json()["error"]["code"] == "STEP_NOT_FOUND"
