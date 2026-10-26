"""Item image, frame image and frame-list routes; the board's current lens."""

import pytest
import respx
from fastapi.testclient import TestClient

from app.ingest import links
from tests.media import image_bytes, video_bytes


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]


def _upload(client: TestClient, board: str, name: str, data: bytes) -> dict:  # type: ignore[type-arg]
    r = client.post(
        f"/api/boards/{board}/items",
        files=[("files", (name, data, "application/octet-stream"))],
    )
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["item"]


def test_image_full_returns_original_bytes(client: TestClient, board: str) -> None:
    data = image_bytes()
    item = _upload(client, board, "a.png", data)
    r = client.get(f"/api/items/{item['id']}/image?size=full")
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "image/png"


def test_image_thumb_and_default(client: TestClient, board: str) -> None:
    item = _upload(client, board, "a.png", image_bytes())
    r = client.get(f"/api/items/{item['id']}/image?size=thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert client.get(f"/api/items/{item['id']}/image").content == r.content


def test_image_bad_size_is_400(client: TestClient, board: str) -> None:
    item = _upload(client, board, "a.png", image_bytes())
    r = client.get(f"/api/items/{item['id']}/image?size=huge")
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_and_removed_items_404(client: TestClient, board: str) -> None:
    r = client.get("/api/items/item_nope/image")
    assert r.status_code == 404 and r.json()["error"]["code"] == "IMAGE_NOT_FOUND"
    item = _upload(client, board, "a.png", image_bytes())
    assert client.delete(f"/api/items/{item['id']}").status_code == 204
    assert client.get(f"/api/items/{item['id']}/image").status_code == 404
    assert client.get(f"/api/items/{item['id']}/frames").status_code == 404


def test_image_missing_file_on_disk_404(client: TestClient, board: str, data_dir) -> None:  # type: ignore[no-untyped-def]
    item = _upload(client, board, "a.png", image_bytes())
    (data_dir / item["storage_path"]).unlink()
    assert client.get(f"/api/items/{item['id']}/image?size=full").status_code == 404


@respx.mock
def test_link_item_has_no_image(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(links, "resolver", lambda host: ["93.184.216.34"])
    respx.get("https://insta.example/x").respond(200, text="<html>login</html>")
    r = client.post(f"/api/boards/{board}/items", json={"url": "https://insta.example/x"})
    item = r.json()["item"]
    assert item["kind"] == "link"
    assert client.get(f"/api/items/{item['id']}/image").status_code == 404


def test_video_frames_list_and_frame_image(client: TestClient, board: str) -> None:
    item = _upload(client, board, "v.mp4", video_bytes([0, 1, 2]))
    r = client.get(f"/api/items/{item['id']}/frames")
    assert r.status_code == 200
    frames = r.json()["frames"]
    assert frames and sum(f["chosen"] for f in frames) == 1
    assert {"id", "t_ms", "chosen"} <= set(frames[0])
    img = client.get(f"/api/items/{item['id']}/frames/{frames[0]['id']}/image")
    assert img.status_code == 200 and img.content[:2] in (b"\xff\xd8", b"RI", b"\x89P")
    # full size of a video item is its chosen frame, never the video bytes
    full = client.get(f"/api/items/{item['id']}/image?size=full")
    assert full.status_code == 200 and full.headers["content-type"].startswith("image/")


def test_frame_of_another_item_404(client: TestClient, board: str) -> None:
    vid = _upload(client, board, "v.mp4", video_bytes([0, 1, 2]))
    img = _upload(client, board, "a.png", image_bytes())
    frame = client.get(f"/api/items/{vid['id']}/frames").json()["frames"][0]
    assert client.get(f"/api/items/{img['id']}/frames/{frame['id']}/image").status_code == 404
    assert client.get(f"/api/items/{vid['id']}/frames/frame_nope/image").status_code == 404


def test_item_dict_includes_parent_item_id(client: TestClient, board: str) -> None:
    item = _upload(client, board, "a.png", image_bytes())
    assert "parent_item_id" in item and item["parent_item_id"] is None


def test_board_lens_null_then_current(client: TestClient) -> None:
    b = client.post("/api/boards", json={"title": "B"}).json()["id"]
    r = client.get(f"/api/boards/{b}/lens")
    assert r.status_code == 200 and r.json() == {"lens": None}
    assert client.get("/api/boards/nope/lens").status_code == 404
    w = client.post("/api/boards", json={"title": "W", "domain": "watch"}).json()["id"]
    client.post(f"/api/boards/{w}/items", files=[("files", ("a.png", image_bytes(), "image/png"))])
    lens = client.get(f"/api/boards/{w}/lens").json()["lens"]
    assert lens["status"] == "confirmed" and lens["origin"] == "curated"
