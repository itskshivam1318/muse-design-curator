import pytest
from fastapi.testclient import TestClient


def board(client: TestClient) -> str:
    return str(client.post("/api/boards", json={"title": "B"}).json()["id"])


def test_list_plugins(client: TestClient) -> None:
    r = client.get("/api/plugins")
    assert r.status_code == 200
    by_id = {p["id"]: p for p in r.json()["plugins"]}
    assert len(by_id) >= 14
    img = by_id["image"]
    assert img["status"] == "available" and img["builtin"] is True
    assert {"name", "description", "mark", "tint", "ink", "runner", "runs_on", "inputs",
            "params", "outputs", "secondary"} <= set(img)  # fmt: skip
    assert "entry" not in img
    assert by_id["video"]["status"] == "not_connected"
    packs = client.get("/api/plugin-packs").json()["packs"]
    assert packs[-1]["id"] == "all"


def test_reload(client: TestClient) -> None:
    r = client.post("/api/plugins/reload")
    assert r.status_code == 200
    assert "image" in r.json()["loaded"] and r.json()["skipped"] == []


def test_board_add_remove_plugin_idempotent(client: TestClient) -> None:
    b = board(client)
    assert client.get(f"/api/boards/{b}/plugins").json() == {"plugin_ids": []}
    for _ in range(2):
        r = client.post(f"/api/boards/{b}/plugins", json={"plugin_id": "image"})
        assert r.status_code in (200, 201)
        assert r.json() == {"plugin_ids": ["image"]}
    client.post(f"/api/boards/{b}/plugins", json={"plugin_id": "critique"})
    assert client.get(f"/api/boards/{b}/plugins").json() == {"plugin_ids": ["critique", "image"]}
    for _ in range(2):
        assert client.delete(f"/api/boards/{b}/plugins/image").status_code == 204
    assert client.get(f"/api/boards/{b}/plugins").json() == {"plugin_ids": ["critique"]}


def test_add_unknown_plugin_404(client: TestClient) -> None:
    b = board(client)
    assert client.post(f"/api/boards/{b}/plugins", json={"plugin_id": "ghost"}).status_code == 404
    assert client.get("/api/boards/nope/plugins").status_code == 404


def test_plugins_disabled_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    b = board(client)
    monkeypatch.setenv("PLUGINS_ENABLED", "0")
    assert client.get("/api/plugins").status_code == 404
    assert client.get("/api/plugin-packs").status_code == 404
    assert client.post("/api/plugins/reload").status_code == 404
    assert client.get(f"/api/boards/{b}/plugins").status_code == 404
    assert client.post(f"/api/boards/{b}/plugins", json={"plugin_id": "image"}).status_code == 404
    assert client.delete(f"/api/boards/{b}/plugins/image").status_code == 404


def test_demo_status_reports_plugins_enabled(client: TestClient) -> None:
    assert client.get("/api/demo/status").json()["plugins_enabled"] is True
