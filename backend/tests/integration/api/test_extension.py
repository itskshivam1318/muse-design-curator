import base64

import pytest
from fastapi.testclient import TestClient

from app.api import extension
from tests.media import image_bytes


@pytest.fixture(autouse=True)
def _reset_code() -> None:
    extension.reset_pair_code()


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]


def pair(client: TestClient) -> str:
    code = client.post("/api/extension/pair-code").json()["code"]
    r = client.post("/api/extension/pair", json={"code": code})
    assert r.status_code == 200
    return r.json()["token"]


def cap(seed: int = 1) -> dict:  # type: ignore[type-arg]
    return {"capture": {"image_b64": base64.b64encode(image_bytes(seed=seed)).decode()}}


def test_pair_code_shape(client: TestClient) -> None:
    body = client.post("/api/extension/pair-code").json()
    assert len(body["code"]) == 6 and body["code"].isdigit()
    assert body["expires_at"]


def test_pair_issues_token_stores_hash_only(client: TestClient) -> None:
    token = pair(client)
    assert len(token) >= 43
    from app.api.deps import get_session
    from app.db.models import ExtensionToken
    from app.main import app

    s = next(app.dependency_overrides[get_session]())
    rows = s.query(ExtensionToken).all()
    assert len(rows) == 1 and rows[0].token_hash != token


def test_wrong_code_and_single_use(client: TestClient) -> None:
    code = client.post("/api/extension/pair-code").json()["code"]
    wrong = "000000" if code != "000000" else "111111"
    r = client.post("/api/extension/pair", json={"code": wrong})
    assert r.status_code == 400 and r.json()["error"]["code"] == "PAIR_CODE_INVALID"
    assert client.post("/api/extension/pair", json={"code": code}).status_code == 200
    r = client.post("/api/extension/pair", json={"code": code})
    assert r.json()["error"]["code"] == "PAIR_CODE_INVALID"


def test_expired_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    code = client.post("/api/extension/pair-code").json()["code"]
    monkeypatch.setattr(extension, "_now", lambda: extension.time.time() + 601)
    r = client.post("/api/extension/pair", json={"code": code})
    assert r.status_code == 400 and r.json()["error"]["code"] == "PAIR_CODE_INVALID"


def test_capture_requires_token(client: TestClient, board: str) -> None:
    r = client.post(f"/api/boards/{board}/items", json=cap())
    assert r.status_code == 401 and r.json()["error"]["code"] == "EXTENSION_UNAUTHORIZED"
    r = client.post(
        f"/api/boards/{board}/items", json=cap(), headers={"Authorization": "Bearer nope"}
    )
    assert r.status_code == 401
    token = pair(client)
    r = client.post(
        f"/api/boards/{board}/items", json=cap(), headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201


def test_uploads_stay_unauthenticated(client: TestClient, board: str) -> None:
    r = client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", ("a.png", image_bytes(seed=3), "image/png"))],
    )
    assert r.status_code == 200


def test_list_boards_newest_first(client: TestClient) -> None:
    a = client.post("/api/boards", json={"title": "A"}).json()["id"]
    b = client.post("/api/boards", json={"title": "B"}).json()["id"]
    client.patch(f"/api/boards/{a}", json={"title": "A2"})
    rows = client.get("/api/boards").json()["boards"]
    assert [r["id"] for r in rows] == [a, b]
    assert set(rows[0]) == {"id", "title", "updated_at"}


def test_cors_allows_extension_origin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import cors_origins

    monkeypatch.setenv("EXTENSION_ORIGIN", "chrome-extension://abc")
    assert "chrome-extension://abc" in cors_origins()
