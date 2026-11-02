"""Vary is retired: every /runs route answers 410 VARY_RETIRED; the tables stay for history."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import VariationRun
from tests.integration.runs.test_orchestrator import make_run, source_with


def body(world: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {
        "source_item_id": source_with(world, world["watch"], "dial_color"),
        "target_key": "dial_color", "mode": "explore", **over,
    }  # fmt: skip


def retired(r: Any) -> bool:
    err = r.json()["error"]
    return bool(
        r.status_code == 410
        and err["code"] == "VARY_RETIRED"
        and err["message"] == "Vary has been replaced by Explore"
    )


def test_runs_return_410(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    old = make_run(world, world["watch"])  # a run from before Vary was retired
    assert retired(client.post(f"/api/boards/{world['watch']}/runs", json=body(world)))
    assert retired(client.post("/api/boards/nope/runs", json={"mode": "explore"}))
    assert retired(client.get(f"/api/runs/{old.id}"))
    assert retired(client.get("/api/runs/nope"))
    assert retired(client.get("/api/corpus/anything/image"))
    s = world["session"]
    s.expire_all()
    assert s.scalar(select(func.count()).select_from(VariationRun)) == 1  # history kept
