from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import events
from tests.integration.api.test_explore import SIX, error, explore, fake, source


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]  # type: ignore[no-any-return]


def test_post_note_201(client: TestClient, board: str) -> None:
    with events.subscribe(board) as sub:
        r = client.post(f"/api/boards/{board}/notes", json={"text": "honey", "x": 5, "y": 6})
        ev = sub.get(timeout=2)
    assert r.status_code == 201
    d = r.json()
    assert (d["kind"], d["note_text"], d["w"], d["h"], d["x"]) == ("note", "honey", 220, 150, 5)
    assert ev and ev["type"] == "item.added" and ev["data"]["id"] == d["id"]


def test_post_note_empty_text_422(client: TestClient, board: str) -> None:
    for text in ("", "x" * 2001):
        r = client.post(f"/api/boards/{board}/notes", json={"text": text, "x": 0, "y": 0})
        assert r.status_code in (400, 422)


def test_patch_note_text(client: TestClient, board: str) -> None:
    n = client.post(f"/api/boards/{board}/notes", json={"text": "a", "x": 0, "y": 0}).json()
    r = client.patch(f"/api/items/{n['id']}", json={"note_text": "b"})
    assert r.status_code == 200 and r.json()["note_text"] == "b"


def test_patch_note_text_on_image_is_400(client: TestClient, world: Any) -> None:
    item = world["items"][world["watch"]][0]
    r = client.patch(f"/api/items/{item}", json={"note_text": "b"})
    assert r.status_code == 400 and error(r) == "NOT_A_NOTE"


def test_explore_on_a_note_is_400(client: TestClient, world: Any) -> None:
    n = client.post(
        f"/api/boards/{world['watch']}/notes", json={"text": "a", "x": 0, "y": 0}
    ).json()
    r = explore(client, n["id"])
    assert r.status_code == 400 and error(r) == "NOT_AN_IMAGE"


def test_explore_prompt_includes_notes(
    client: TestClient, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = fake(monkeypatch, SIX)
    client.post(
        f"/api/boards/{world['watch']}/notes",
        json={"text": "honey, like old paper", "x": 0, "y": 0},
    )
    assert explore(client, source(world)).status_code == 200
    assert "Notes on the board:" in f.prompts[0] and "honey, like old paper" in f.prompts[0]
