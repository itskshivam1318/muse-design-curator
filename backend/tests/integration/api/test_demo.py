"""DEMO_MODE guard: locked writes, open routes, unlock and its cookie, the visitor limiter."""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import demo
from app.config import Settings
from app.db.repos import runs as runs_repo
from tests.integration.runs.test_orchestrator import make_run

PASSCODE = "open sesame"
SECRET = "s" * 32


class Clock:
    def __init__(self) -> None:
        self.t = time.time()  # run rows carry real timestamps

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(demo, "now", c)
    return c


@pytest.fixture(autouse=True)
def demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", PASSCODE)
    monkeypatch.setenv("DEMO_SECRET", SECRET)


def unlock(client: TestClient, passcode: str = PASSCODE):  # type: ignore[no-untyped-def]
    return client.post("/api/demo/unlock", json={"passcode": passcode})


def locked(r: Any) -> bool:
    return r.status_code == 403 and r.json()["error"] == {
        "code": "DEMO_LOCKED",
        "message": "This is a read-only demo. Enter the passcode to add references.",
    }


def test_startup_requires_passcode_and_secret() -> None:
    demo.check_settings(Settings(DEMO_MODE=False))
    demo.check_settings(Settings(DEMO_MODE=True, DEMO_PASSCODE="p", DEMO_SECRET="s"))
    with pytest.raises(RuntimeError):
        demo.check_settings(Settings(DEMO_MODE=True, DEMO_PASSCODE="p", DEMO_SECRET=None))
    with pytest.raises(RuntimeError):
        demo.check_settings(Settings(DEMO_MODE=True, DEMO_PASSCODE=None, DEMO_SECRET="s"))


def test_locked_writes_return_403(client: TestClient, world: dict[str, Any]) -> None:
    board = world["watch"]
    item = world["items"][board][0]
    attempts = [
        client.post("/api/boards", json={"title": "x"}),
        client.patch(f"/api/boards/{board}", json={"title": "y"}),
        client.post(f"/api/boards/{board}/items", json={"url": "https://example.com/"}),
        client.post(f"/api/boards/{board}/items", files=[("files", ("a.png", b"x", "image/png"))]),
        client.delete(f"/api/items/{item}"),
        client.patch(f"/api/items/{item}", json={"role": "counter_example"}),
        client.patch(f"/api/items/{item}", json={"x": 1, "chosen_frame_id": "frm_x"}),
        client.post(f"/api/items/{item}/parse"),
        client.post(f"/api/boards/{board}/lens:propose"),
        client.put(f"/api/boards/{board}/lens"),
        client.patch(f"/api/items/{item}/attributes/dial_color", json={"value": "red"}),
        client.post("/api/extension/pair-code"),
        client.post("/api/extension/pair", json={"code": "123456"}),
    ]
    assert all(locked(r) for r in attempts), [r.status_code for r in attempts]


def test_open_routes_work_while_locked(client: TestClient, world: dict[str, Any]) -> None:
    board = world["watch"]
    item = world["items"][board][0]
    assert client.get("/api/demo/status").json() == {"demo_mode": True, "unlocked": False, "explore_enabled": True, "plugins_enabled": True}
    for path in ("/api/boards", f"/api/boards/{board}", f"/api/boards/{board}/items",
                 f"/api/boards/{board}/profile", f"/api/boards/{board}/lens",
                 f"/api/items/{item}/attributes", f"/api/items/{item}/image?size=thumb"):  # fmt: skip
        assert client.get(path).status_code == 200, path
    moved = client.patch(f"/api/items/{item}", json={"x": 12, "y": 34, "z": 5})
    assert moved.status_code == 200 and moved.json()["x"] == 12
    run = make_run(world, board)  # a run from before Vary was retired
    top = next(c for c in runs_repo.candidates(world["session"], run.id) if c.rank is not None)
    r = client.post(f"/api/runs/{run.id}/candidates/{top.id}/decisions", json={"decision": "keep"})
    assert r.status_code == 201


def test_unlock_success_opens_writes(client: TestClient, clock: Clock) -> None:
    r = unlock(client)
    assert r.status_code == 200 and r.json()["unlocked"] is True
    cookie = r.headers["set-cookie"]
    assert "dle_demo=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Max-Age=43200" in cookie and "Secure" not in cookie  # plain http in tests
    assert client.get("/api/demo/status").json() == {"demo_mode": True, "unlocked": True, "explore_enabled": True, "plugins_enabled": True}
    assert client.post("/api/boards", json={"title": "mine"}).status_code == 201


def test_secure_cookie_behind_https_proxy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_TRUST_PROXY", "1")
    r = client.post("/api/demo/unlock", json={"passcode": PASSCODE},
                    headers={"X-Forwarded-Proto": "https"})  # fmt: skip
    assert "Secure" in r.headers["set-cookie"]


def test_wrong_passcode_and_lockout(client: TestClient, clock: Clock) -> None:
    for _ in range(5):
        r = unlock(client, "nope")
        assert r.status_code == 401 and r.json()["error"]["code"] == "DEMO_PASSCODE_INVALID"
    r = unlock(client)  # even the right passcode waits out the lockout
    assert r.status_code == 429 and r.json()["error"]["code"] == "DEMO_RATE_LIMITED"
    assert "Try again in" in r.json()["error"]["message"]
    clock.t += demo.UNLOCK_WINDOW_S + 1
    assert unlock(client).status_code == 200


def test_cookie_expiry_and_tamper(clock: Clock) -> None:
    good = demo.make_cookie(SECRET, int(clock.t) + 60)
    assert demo.cookie_valid(SECRET, good)
    assert not demo.cookie_valid("other-secret", good)
    expiry, sig = good.split(".")
    assert not demo.cookie_valid(SECRET, f"{int(expiry) + 3600}.{sig}")  # extended expiry
    flipped = "1" if sig[-1] == "0" else "0"  # always a different last character
    assert not demo.cookie_valid(SECRET, f"{expiry}.{sig[:-1]}{flipped}")
    assert not demo.cookie_valid(SECRET, "garbage")
    assert not demo.cookie_valid(SECRET, None)
    clock.t += 61
    assert not demo.cookie_valid(SECRET, good)


def test_expired_cookie_is_locked_again(client: TestClient, clock: Clock) -> None:
    unlock(client)
    assert client.post("/api/boards", json={"title": "a"}).status_code == 201
    clock.t += demo.COOKIE_TTL_S + 1
    assert locked(client.post("/api/boards", json={"title": "b"}))


def test_proxy_header_ignored_unless_trusted(world: dict[str, Any]) -> None:
    from starlette.requests import Request

    req = Request({"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")],
                   "client": ("9.9.9.9", 1), "method": "GET", "path": "/"})  # fmt: skip
    assert demo.client_ip(req, Settings(DEMO_TRUST_PROXY=False)) == "9.9.9.9"
    assert demo.client_ip(req, Settings(DEMO_TRUST_PROXY=True)) == "1.2.3.4"


def test_demo_off_changes_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "0")
    assert client.get("/api/demo/status").json() == {"demo_mode": False, "unlocked": True, "explore_enabled": True, "plugins_enabled": True}
    assert client.post("/api/boards", json={"title": "x"}).status_code == 201
    assert unlock(client).json()["error"]["code"] == "DEMO_MODE_OFF"


def test_status_reports_explore_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPLORE_ENABLED", "0")
    assert client.get("/api/demo/status").json()["explore_enabled"] is False


def _req(xff: str | None) -> Any:
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": ("9.9.9.9", 1),
                    "method": "GET", "path": "/"})  # fmt: skip


def test_client_ip_uses_rightmost_trusted_hop_not_spoofable_left() -> None:
    trust = Settings(DEMO_TRUST_PROXY=True, DEMO_PROXY_HOPS=1)
    real = demo.client_ip(_req("203.0.113.7"), trust)
    assert real == "203.0.113.7"
    # a client prepending fake addresses does not change the limiter key
    for fake in ("1.1.1.1", "1.1.1.1, 2.2.2.2", "evil"):
        assert demo.client_ip(_req(f"{fake}, 203.0.113.7"), trust) == real
    two = Settings(DEMO_TRUST_PROXY=True, DEMO_PROXY_HOPS=2)
    assert demo.client_ip(_req("6.6.6.6, 203.0.113.7, 10.0.0.2"), two) == "203.0.113.7"
    assert demo.client_ip(_req("10.0.0.2"), two) == "9.9.9.9"  # too few hops: connection address
    assert demo.client_ip(_req(None), trust) == "9.9.9.9"
    off = Settings(DEMO_TRUST_PROXY=False)
    assert demo.client_ip(_req("1.1.1.1, 203.0.113.7"), off) == "9.9.9.9"


def test_non_ascii_cookie_is_locked_not_500(client: TestClient) -> None:
    assert not demo.cookie_valid(SECRET, "4102444800.é" + "a" * 63)
    raw = [(b"cookie", "dle_demo=4102444800.éé".encode())]  # raw UTF-8 bytes, not ASCII
    status = client.get("/api/demo/status", headers=raw)
    assert status.json() == {"demo_mode": True, "unlocked": False, "explore_enabled": True, "plugins_enabled": True}
    assert locked(client.post("/api/boards", json={"title": "x"}, headers=raw))


def test_expired_window_keys_are_pruned(clock: Clock) -> None:
    demo.windows.add("run:1.2.3.4")
    assert demo.windows.retry_after("run:1.2.3.4", 3600, 5) is None
    assert "run:1.2.3.4" in demo.windows._hits
    clock.t += 3601
    assert demo.windows.retry_after("run:1.2.3.4", 3600, 5) is None
    assert "run:1.2.3.4" not in demo.windows._hits
    # a probe of a key that never had hits leaves nothing behind
    demo.windows.retry_after("run:9.9.9.9", 3600, 5)
    assert "run:9.9.9.9" not in demo.windows._hits
