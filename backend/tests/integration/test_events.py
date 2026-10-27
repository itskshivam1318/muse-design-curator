import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import events, jobs
from app.api import deps
from app.board import profile as profile_mod
from app.board import profile_hook
from app.db.models import Lens
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.repos import profiles as profiles_repo
from app.domain.lens import LensSpec
from app.main import app

LENS = {
    "id": "thing@1", "domain": "thing", "label": "Thing", "origin": "edited", "parts": [],
    "attributes": [
        {"key": "finish", "label": "Finish", "category": "c", "kind": "enum",
         "vocabulary": ["brushed", "polished"]},
        {"key": "size_mm", "label": "Size", "category": "c", "kind": "number",
         "unit": "mm", "min": 0, "max": 100, "tolerance": 5},
        {"key": "accent", "label": "Accent", "category": "c", "kind": "color"},
        {"key": "note", "label": "Note", "category": "c", "kind": "text"},
    ],
}  # fmt: skip


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    s = deps._factory()()
    yield s
    s.close()


def seed(s: Session) -> tuple[str, list[str]]:
    b = boards_repo.create(s, "B", context="", domain=None)
    spec = LensSpec.model_validate(LENS)
    from app.db.repos import lenses as lenses_repo

    row = lenses_repo.save(
        s, b.id, "thing", "edited", spec.model_dump(mode="json"), status="confirmed"
    )
    b.lens_id = row.id
    ids = []
    for _ in range(4):
        it = items_repo.create(
            s, board_id=b.id, kind="image", origin="upload", parse_status="completed"
        )
        attrs_repo.upsert(
            s, it.id, "finish", label="Finish", category="c", kind="enum", part=None,
            value_json="brushed", confidence=0.9, status="auto", source="model",
            enabled=True,
        )  # fmt: skip
        ids.append(it.id)
    s.commit()
    return b.id, ids


def test_edit_triggers_recompute_and_newer_version(db: Session) -> None:
    board_id, ids = seed(db)
    v1 = profile_mod.recompute(db, board_id)
    db.commit()
    assert v1 == 1
    assert profile_mod.recompute(db, board_id) is None  # unchanged: no new version
    # edit arrives after the first recompute
    attrs_repo.upsert(db, ids[0], "finish", value_json="polished", confidence=1.0, status="edited")
    db.commit()
    profile_hook.request_recompute(board_id)  # JOBS_SYNC: synchronous, own session
    db.expire_all()
    row = profiles_repo.latest(db, board_id)
    assert row is not None and row.version == 2
    assert row.profile_json["attributes"]["finish"]["distribution"] == {"brushed": 3, "polished": 1}


def test_recompute_publishes_after_commit(db: Session) -> None:
    board_id, _ = seed(db)
    with events.subscribe(board_id) as sub:
        profile_mod.recompute(db, board_id)
        assert sub.get(timeout=0.1) is None  # nothing before commit
        db.commit()
        ev = sub.get(timeout=1)
    assert ev is not None and ev["type"] == "profile.updated"
    assert ev["data"]["version"] == 1 and "attributes" in ev["data"]["profile"]


def test_debounce_coalesces_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBS_SYNC", "0")
    calls: list[str] = []
    monkeypatch.setattr(profile_hook, "DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(profile_hook, "_run_recompute", calls.append)
    for _ in range(5):
        profile_hook.request_recompute("b1")
    import time

    time.sleep(0.3)
    assert calls == ["b1"]


def test_role_change_and_delete_request_recompute(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board_id, ids = seed(db)
    called: list[str] = []
    monkeypatch.setattr(profile_hook, "request_recompute", called.append)
    assert client.patch(f"/api/items/{ids[0]}", json={"role": "counter_example"}).status_code == 200
    assert called == [board_id]
    assert client.delete(f"/api/items/{ids[1]}").status_code == 204
    assert called == [board_id, board_id]


def _stream(board_id: str, n: int, publish: Any) -> list[tuple[str | None, str | None, str]]:
    """Drive the ASGI app in-process, read n events, then disconnect."""
    got: list[tuple[str | None, str | None, str]] = []

    async def go() -> None:
        disconnected = asyncio.Event()
        sent = asyncio.Event()
        buf = ""

        async def receive() -> dict[str, Any]:
            if not sent.is_set():
                sent.set()
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(msg: dict[str, Any]) -> None:
            nonlocal buf
            if msg["type"] != "http.response.body":
                return
            buf += msg.get("body", b"").decode().replace("\r\n", "\n")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                f = dict(
                    ln.split(": ", 1) for ln in block.split("\n") if ": " in ln and ln[0] != ":"
                )
                if f:
                    got.append((f.get("id"), f.get("event"), f.get("data", "")))
                if len(got) >= n:
                    disconnected.set()

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "path": f"/api/boards/{board_id}/events", "raw_path": b"", "query_string": b"",
            "headers": [], "server": ("t", 80), "client": ("t", 1), "scheme": "http",
            "root_path": "",
        }  # fmt: skip
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.sleep(0.3)
        await asyncio.get_running_loop().run_in_executor(None, publish)
        await asyncio.wait_for(task, 10)

    asyncio.run(go())
    return got


def test_sse_delivers_item_parsed_then_profile_updated_in_order(
    client: TestClient, db: Session
) -> None:
    board_id, _ = seed(db)
    profile_mod.recompute(db, board_id)
    db.commit()

    def publish() -> None:
        events.publish(board_id, "item.parsed", {"id": "x"})
        events.publish(board_id, "profile.updated", {"version": 2, "profile": {}})

    got = _stream(board_id, 3, publish)
    assert [g[1] for g in got] == ["profile.updated", "item.parsed", "profile.updated"]
    assert json.loads(got[0][2])["version"] == 1  # snapshot first
    ids = [int(g[0]) for g in got if g[0] is not None]
    assert ids == sorted(ids) and len(set(ids[1:])) == len(ids[1:])
    assert not events._subs  # unsubscribed on disconnect


def test_get_profile_endpoint(client: TestClient, db: Session) -> None:
    board_id, _ = seed(db)
    assert client.get(f"/api/boards/{board_id}/profile").json()["version"] == 0
    profile_mod.recompute(db, board_id)
    db.commit()
    body = client.get(f"/api/boards/{board_id}/profile").json()
    assert body["version"] == 1 and body["profile"]["signals"][0]["key"] == "finish"
    assert client.get("/api/boards/nope/profile").status_code == 404


_ = (jobs, Lens)


def test_attribute_edit_route_recomputes_and_publishes(client: TestClient, db: Session) -> None:
    board_id, ids = seed(db)
    profile_mod.recompute(db, board_id)
    db.commit()
    with events.subscribe(board_id) as sub:
        r = client.patch(f"/api/items/{ids[0]}/attributes/finish", json={"value": "polished"})
        assert r.status_code == 200
        seen = []
        while (ev := sub.get(timeout=1)) is not None:
            seen.append(ev)
            if ev["type"] == "profile.updated":
                break
    assert [e["type"] for e in seen][-1] == "profile.updated"
    assert seen[-1]["data"]["version"] == 2
    db.expire_all()
    row = profiles_repo.latest(db, board_id)
    assert row is not None and row.version == 2
    assert row.profile_json["attributes"]["finish"]["distribution"] == {"brushed": 3, "polished": 1}
    # confirm / disable also recompute
    for body in ({"action": "disable"}, {"action": "enable"}):
        assert client.patch(f"/api/items/{ids[1]}/attributes/finish", json=body).status_code == 200
    db.expire_all()
    latest = profiles_repo.latest(db, board_id)
    assert latest is not None and latest.version >= 3


@pytest.mark.parametrize("key", ["finish", "size_mm", "accent", "note"])
def test_bool_value_patch_is_400_not_500(client: TestClient, db: Session, key: str) -> None:
    _, ids = seed(db)
    for bad in (True, False):
        r = client.patch(f"/api/items/{ids[0]}/attributes/{key}", json={"value": bad})
        assert r.status_code == 400, (key, r.status_code)
        assert r.json()["error"]["code"] == "INVALID_ATTRIBUTE_VALUE"


class _Conn:
    """One in-process SSE connection driven through the ASGI app."""

    def __init__(self, board_id: str, ip: str) -> None:
        self.board_id, self.ip = board_id, ip
        self.status: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.gone = asyncio.Event()
        self._sent = False
        self.task: asyncio.Task[None] | None = None

    async def _receive(self) -> dict[str, Any]:
        if not self._sent:
            self._sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.gone.wait()
        return {"type": "http.disconnect"}

    async def _send(self, msg: dict[str, Any]) -> None:
        if msg["type"] == "http.response.start" and not self.status.done():
            self.status.set_result(msg["status"])

    def start(self) -> "_Conn":
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "path": f"/api/boards/{self.board_id}/events", "raw_path": b"", "query_string": b"",
            "headers": [], "server": ("t", 80), "client": (self.ip, 1), "scheme": "http",
            "root_path": "",
        }  # fmt: skip
        self.task = asyncio.create_task(app(scope, self._receive, self._send))
        return self

    async def close(self) -> None:
        self.gone.set()
        assert self.task is not None
        await asyncio.wait_for(self.task, 10)


async def _get(path: str) -> int:
    status: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        if msg["type"] == "http.response.start":
            status.append(msg["status"])

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "path": path, "raw_path": b"", "query_string": b"", "headers": [],
        "server": ("t", 80), "client": ("10.9.9.9", 1), "scheme": "http", "root_path": "",
    }  # fmt: skip
    await app(scope, receive, send)
    return status[0]


def test_many_open_streams_hold_no_threadpool_worker(client: TestClient, db: Session) -> None:
    import anyio.to_thread

    board_id, _ = seed(db)

    async def go() -> None:
        conns = [_Conn(board_id, f"10.0.{i // 3}.{i % 3}").start() for i in range(50)]
        assert {await asyncio.wait_for(c.status, 10) for c in conns} == {200}
        await asyncio.sleep(1.2)  # several poll intervals
        limiter = anyio.to_thread.current_default_thread_limiter()
        assert limiter.borrowed_tokens == 0  # an idle stream holds no worker
        t0 = asyncio.get_running_loop().time()
        assert await asyncio.wait_for(_get(f"/api/boards/{board_id}"), 5) == 200
        assert asyncio.get_running_loop().time() - t0 < 2
        events.publish(board_id, "item.parsed", {"id": "x"})
        for c in conns:
            await c.close()

    asyncio.run(go())
    assert not events._subs


def test_stream_caps_per_ip_and_global_release_on_disconnect(
    client: TestClient, db: Session
) -> None:
    board_id, _ = seed(db)

    async def go() -> None:
        mine = [_Conn(board_id, "10.1.1.1").start() for _ in range(3)]
        assert [await asyncio.wait_for(c.status, 10) for c in mine] == [200, 200, 200]
        extra = _Conn(board_id, "10.1.1.1").start()
        assert await asyncio.wait_for(extra.status, 10) == 429
        await asyncio.wait_for(extra.task, 10)  # type: ignore[arg-type]
        await mine[0].close()
        again = _Conn(board_id, "10.1.1.1").start()
        assert await asyncio.wait_for(again.status, 10) == 200
        # global cap: 50 open streams in all
        others = [_Conn(board_id, f"10.2.{i // 3}.{i % 3}").start() for i in range(47)]
        assert {await asyncio.wait_for(c.status, 10) for c in others} == {200}
        over = _Conn(board_id, "10.3.3.3").start()
        assert await asyncio.wait_for(over.status, 10) == 429
        await asyncio.wait_for(over.task, 10)  # type: ignore[arg-type]
        for c in [*mine[1:], again, *others]:
            await c.close()
        last = _Conn(board_id, "10.3.3.3").start()
        assert await asyncio.wait_for(last.status, 10) == 200
        await last.close()

    asyncio.run(go())
    assert not events._subs


def test_too_many_streams_error_body(client: TestClient, db: Session) -> None:
    from app.board import events as board_events

    board_id, _ = seed(db)
    held = [board_events.acquire_slot("testclient") for _ in range(3)]  # TestClient's host
    try:
        r = client.get(f"/api/boards/{board_id}/events")
        assert r.status_code == 429 and r.json()["error"]["code"] == "TOO_MANY_STREAMS"
    finally:
        for h in held:
            h.release()
