"""Visualize a note: text to image beside the note, parsed and checked."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo, events
from app.db.models import BoardItem
from app.explore.visualize import _iso
from app.notes import visualize
from app.providers.reliability import ModelError
from tests.integration.api.test_explore import error


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    from app.api import deps

    s = deps._factory()()
    yield s
    s.close()


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]  # type: ignore[no-any-return]


def make_note(client: TestClient, board: str, text: str = "a honey jar") -> dict[str, Any]:
    r = client.post(f"/api/boards/{board}/notes", json={"text": text, "x": 100, "y": 50})
    return r.json()  # type: ignore[no-any-return]


def children(session: Session, note_id: str) -> list[BoardItem]:
    session.expire_all()
    q = select(BoardItem).where(BoardItem.parent_item_id == note_id).order_by(BoardItem.id)
    return list(session.scalars(q))


def test_visualize_creates_generated_item_beside_note(
    client: TestClient, board: str, db: Session
) -> None:
    note = make_note(client, board)
    r = client.post(f"/api/items/{note['id']}/visualize")
    assert r.status_code == 202 and r.json() == {"note_id": note["id"], "status": "visualizing"}
    (item,) = children(db, note["id"])
    assert (item.kind, item.origin, item.rights_status) == ("image", "generated", "generated")
    assert (item.x, item.y) == (100 + 220 + 40, 50)
    assert item.staged is False
    assert item.generation_json["from"] == "note" and "honey jar" in item.generation_json["prompt"]
    assert item.parse_status != "failed"  # a bare board has no lens yet: parsing waits
    assert set(item.check_json) == {"target_ok", "answer"}
    note_row = db.get(BoardItem, note["id"])
    db.refresh(note_row)
    assert note_row.generation_json is None  # claim cleared


def test_visualize_publishes_events(client: TestClient, board: str) -> None:
    note = make_note(client, board)
    with events.subscribe(board) as sub:
        client.post(f"/api/items/{note['id']}/visualize")
        seen = []
        while (ev := sub.get(timeout=1)) is not None:
            seen.append(ev["type"])
            if ev["type"] == "note.visualized":
                assert ev["data"]["note_id"] == note["id"] and ev["data"]["item_id"]
                break
    assert seen[0] == "note.visualizing"
    assert seen.index("item.added") < seen.index("item.updated") < seen.index("note.visualized")


def test_second_visualize_stacks_below(client: TestClient, board: str, db: Session) -> None:
    note = make_note(client, board)
    client.post(f"/api/items/{note['id']}/visualize")
    client.post(f"/api/items/{note['id']}/visualize")
    a, b = children(db, note["id"])
    assert b.x == a.x and b.y == pytest.approx(a.y + a.h + 24)


def test_visualize_conflict_409_then_stale_claim_allowed(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(visualize.jobs, "enqueue", lambda *_a, **_k: None)  # job never runs
    note = make_note(client, board)
    assert client.post(f"/api/items/{note['id']}/visualize").status_code == 202
    r = client.post(f"/api/items/{note['id']}/visualize")
    assert r.status_code == 409 and error(r) == "NOTE_VISUALIZING"
    row = db.get(BoardItem, note["id"])
    old = _iso(datetime.now(UTC) - timedelta(seconds=301))
    row.generation_json = {"visualizing_since": old}
    db.commit()
    assert client.post(f"/api/items/{note['id']}/visualize").status_code == 202


def test_not_found_and_not_a_note(client: TestClient, board: str, world: Any) -> None:
    r = client.post("/api/items/nope/visualize")
    assert r.status_code == 404
    img = world["items"][world["watch"]][0]
    r = client.post(f"/api/items/{img}/visualize")
    assert r.status_code == 400 and error(r) == "NOT_A_NOTE"


def test_failure_leaves_no_item_and_clears_claim(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        model = "broken"

        def generate(self, prompt: str) -> bytes:
            raise ModelError("MODEL_UNAVAILABLE", message="down")

    monkeypatch.setattr(visualize, "get_image_provider", lambda _s: Broken())
    note = make_note(client, board)
    with events.subscribe(board) as sub:
        assert client.post(f"/api/items/{note['id']}/visualize").status_code == 202
        types = []
        while (ev := sub.get(timeout=1)) is not None:
            types.append(ev["type"])
            if ev["type"] == "note.visualize_failed":
                assert ev["data"] == {"note_id": note["id"], "error": "MODEL_UNAVAILABLE"}
                break
    assert "note.visualize_failed" in types and "item.added" not in types
    assert children(db, note["id"]) == []
    row = db.get(BoardItem, note["id"])
    db.refresh(row)
    assert row.generation_json is None
    assert client.post(f"/api/items/{note['id']}/visualize").status_code == 202


def test_recover_stuck_notes_frees_claims(client: TestClient, board: str, db: Session) -> None:
    note = make_note(client, board)
    row = db.get(BoardItem, note["id"])
    row.generation_json = {"visualizing_since": _iso(datetime.now(UTC))}
    db.commit()
    assert visualize.recover_stuck_notes(db) == 1
    db.commit()
    db.refresh(row)
    assert row.generation_json is None


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)


def test_demo_mode_requires_unlock(demo_on: None, client: TestClient) -> None:
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    board = client.post("/api/boards", json={"title": "B"}).json()["id"]
    note = make_note(client, board)
    client.cookies.clear()
    r = client.post(f"/api/items/{note['id']}/visualize")
    assert r.status_code == 403 and error(r) == "DEMO_LOCKED"
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    assert client.post(f"/api/items/{note['id']}/visualize").status_code == 202
