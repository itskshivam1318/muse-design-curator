from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "live": False, "reason": "mock providers"}


def test_health_reports_missing_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("REASONING_PROVIDER", "muse-spark")
    monkeypatch.setenv("MODEL_API_KEY", "")
    body = TestClient(app).get("/api/health").json()
    assert body == {"ok": True, "live": False, "reason": "MODEL_API_KEY not set"}


def test_health_live_with_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("REASONING_PROVIDER", "muse-spark")
    monkeypatch.setenv("MODEL_API_KEY", "k")
    assert TestClient(app).get("/api/health").json() == {"ok": True, "live": True}
