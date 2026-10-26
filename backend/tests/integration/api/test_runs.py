from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import VariationRun
from app.db.repos import decisions as decisions_repo
from tests.integration.runs.test_orchestrator import source_with


def body(world: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {
        "source_item_id": source_with(world, world["watch"], "dial_color"),
        "target_key": "dial_color", "mode": "explore", **over,
    }  # fmt: skip


def post(client: TestClient, world: dict[str, Any], key: str | None = None, **over: Any):  # type: ignore[no-untyped-def]
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/boards/{world['watch']}/runs", json=body(world, **over),
                       headers=headers)  # fmt: skip


def test_post_returns_202_and_get_shape(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = post(client, world)
    assert r.status_code == 202 and set(r.json()) == {"run_id"}
    got = client.get(f"/api/runs/{r.json()['run_id']}").json()
    assert set(got) == {
        "run", "progress", "summary", "results", "needs_review", "rejected", "excluded_counts",
    }  # fmt: skip
    assert got["run"]["status"] == "completed" and got["run"]["ranking_version"] == "rank-2026.10-c"
    assert got["progress"]["stage"] == "completed"
    assert got["summary"]["returned"] == len(got["results"]) and 0 < len(got["results"]) <= 6
    assert got["excluded_counts"] == got["summary"]["excluded"]
    assert len(got["needs_review"]) <= 6
    top = got["results"][0]
    assert top["rank"] == 1 and top["state"] == "validated"
    assert set(top["provenance"]) == {"credit", "landing_url", "license_code", "creator_name"}
    assert top["provenance"]["license_code"] == "CC0-1.0"
    assert "test fixtures" in top["provenance"]["credit"]
    assert {"target", "preservation", "relevance", "diversity", "total"} <= set(top["scores"])
    assert {c["check"] for c in top["checks"]} >= {"provenance", "duplicate", "target"}
    assert all({"verdict", "reason", "evidence"} <= set(c) for c in top["checks"])
    assert top["observed_target_value"] is not None
    assert top["decision"] is None and top["decisions"] == []
    img = client.get(top["image_url"])
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")


def test_decision_history_in_candidate_view(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    rid = post(client, world).json()["run_id"]
    top = client.get(f"/api/runs/{rid}").json()["results"][0]
    s = world["session"]
    for d in ("keep", "reject"):
        decisions_repo.append(
            s, board_id=world["watch"], run_id=rid, run_candidate_id=top["id"],
            corpus_item_id=top["corpus_item_id"], decision=d,
        )  # fmt: skip
    s.commit()
    again = client.get(f"/api/runs/{rid}").json()["results"][0]
    assert again["decision"]["decision"] == "reject"
    assert [d["decision"] for d in again["decisions"]] == ["reject", "keep"]


def test_idempotency_header(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    a = post(client, world, key="abc")
    b = post(client, world, key="abc")
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    c = post(client, world, key="abc", mode="avoid", target_values=["red"])
    assert c.status_code == 409 and c.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    s = world["session"]
    s.expire_all()
    assert s.scalar(select(func.count()).select_from(VariationRun)) == 1
    d, e = post(client, world), post(client, world)  # no header: two independent runs
    assert d.json()["run_id"] != e.json()["run_id"]


def test_errors(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = post(client, world, target_key="nope")
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_ATTRIBUTE"
    s = world["session"]
    s.expire_all()
    assert s.scalar(select(func.count()).select_from(VariationRun)) == 0
    assert client.get("/api/runs/nope").status_code == 404
    r = client.post("/api/boards/nope/runs", json=body(world))
    assert r.status_code == 404 and r.json()["error"]["code"] == "BOARD_NOT_FOUND"
    r = client.post(f"/api/boards/{world['watch']}/runs", json={"mode": "explore"})
    assert r.status_code == 400


def test_stale_run_fails_on_read(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    rid = post(client, world).json()["run_id"]
    s = world["session"]
    s.expire_all()
    run = s.get(VariationRun, rid)
    run.status = "validating"
    run.created_at = (datetime.now(UTC) - timedelta(minutes=6)).isoformat(timespec="milliseconds")
    s.commit()
    got = client.get(f"/api/runs/{rid}").json()
    assert got["run"]["status"] == "failed" and got["run"]["error_code"] == "RUN_INTERRUPTED"
    s.expire_all()
    assert s.get(VariationRun, rid).error_code == "RUN_INTERRUPTED"
