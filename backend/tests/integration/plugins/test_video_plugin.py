"""Animate: frames go to fal image-to-video; the clip comes back as a video item."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import demo
from app.config import get_settings
from app.db.models import BoardItem
from app.providers import get_fal
from app.providers.fal import MockFal
from tests.integration.api.test_nodes_api import (
    add_plugin,
    make_node,
    make_note,
    run_node,
    upload_image,
)
from tests.media import video_bytes

VIDEO_URL = "https://v3.fal.media/files/clip.mp4"


@pytest.fixture(autouse=True)
def fal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setenv("FAL_POLL_S", "0")


@pytest.fixture
def fal() -> MockFal:
    mock = get_fal(get_settings())
    assert isinstance(mock, MockFal)
    mock.statuses = ["IN_QUEUE", "COMPLETED"]
    st = get_settings()
    for ep in (st.FAL_VIDEO_STANDARD, st.FAL_VIDEO_PRO):
        mock.results[ep] = {"video": {"url": VIDEO_URL}}
    mock.files[VIDEO_URL] = video_bytes([1], seg_seconds=1.0)
    return mock


def start(client: TestClient, board: str, params: dict[str, Any] | None = None) -> tuple[str, str]:
    add_plugin(client, board, "video")
    src = upload_image(client, board, seed=1)
    node = make_node(client, board, "video", [src])
    body = {"prompt": "slow push in", **(params or {})}
    assert client.patch(f"/api/nodes/{node['id']}", json={"params": body}).status_code == 200
    return src, node["id"]


def submits(fal: MockFal) -> list[Any]:
    return [c[1] for c in fal.calls if c[0] == "submit"]


def hits(board: str) -> int:
    return len(demo.windows._hits.get(f"video:{board}", ()))


@pytest.mark.parametrize("kind", ["standard", "pro"])
def test_video_endpoint_by_type(client: TestClient, board: str, fal: MockFal, kind: str) -> None:
    _, node = start(client, board, {"type": kind, "duration": 10})
    run = run_node(client, node)
    assert run["status"] == "done", (run["error_code"], run["error_message"])
    st = get_settings()
    (ep, body) = submits(fal)[0]
    assert ep == (st.FAL_VIDEO_PRO if kind == "pro" else st.FAL_VIDEO_STANDARD)
    assert body["duration"] == "10" and body["prompt"] == "slow push in"
    if kind == "pro":
        assert "start_image_url" in body and "image_url" not in body
        assert body["generate_audio"] is False
    else:
        assert "image_url" in body and "start_image_url" not in body
        assert "generate_audio" not in body


@pytest.mark.parametrize(
    "kind,fields", [("standard", ("image_url", "tail_image_url")),
                    ("pro", ("start_image_url", "end_image_url"))]
)  # fmt: skip
def test_video_sends_start_and_end_urls(
    client: TestClient, board: str, fal: MockFal, kind: str, fields: tuple[str, str]
) -> None:
    _src, node = start(client, board, {"type": kind})
    end = upload_image(client, board, seed=2)
    client.patch(f"/api/nodes/{node}", json={"params": {"prompt": "x", "type": kind, "end": end}})
    run = run_node(client, node)
    assert run["status"] == "done", (run["error_code"], run["error_message"])
    body = submits(fal)[0][1]
    assert body[fields[0]] in fal.files and body[fields[1]] in fal.files
    assert body[fields[0]] != body[fields[1]]
    assert fal.count("upload") == 2


def test_video_no_end_frame_sends_none(client: TestClient, board: str, fal: MockFal) -> None:
    _, node = start(client, board)
    assert run_node(client, node)["status"] == "done"
    assert "tail_image_url" not in submits(fal)[0][1] and fal.count("upload") == 1


def test_video_swap_order_respected(client: TestClient, board: str, fal: MockFal) -> None:
    src, node = start(client, board)
    other = upload_image(client, board, seed=2)
    p = {"prompt": "x", "start": other, "end": src}
    client.patch(f"/api/nodes/{node}", json={"params": p})
    assert run_node(client, node)["status"] == "done"
    body = submits(fal)[0][1]
    ups = [c[1] for c in fal.calls if c[0] == "upload"]
    assert len(ups) == 2
    r = client.get(f"/api/items/{other}/image", params={"size": "full"})
    assert fal.files[body["image_url"]] == r.content
    r2 = client.get(f"/api/items/{src}/image", params={"size": "full"})
    assert fal.files[body["tail_image_url"]] == r2.content


@pytest.mark.parametrize("bad", ["deleted", "note", "other-board", "unknown"])
def test_video_bad_end_frame_no_submit(
    client: TestClient, board: str, db: Session, fal: MockFal, bad: str
) -> None:
    _src, node = start(client, board)
    if bad == "deleted":
        end = upload_image(client, board, seed=2)
        assert client.delete(f"/api/items/{end}").status_code in (200, 204)
    elif bad == "note":
        end = make_note(client, board)
    elif bad == "other-board":
        other = client.post("/api/boards", json={"title": "B"}).json()["id"]
        end = upload_image(client, other, seed=3)
    else:
        end = "item_nope"
    client.patch(f"/api/nodes/{node}", json={"params": {"prompt": "x", "end": end}})
    run = run_node(client, node)
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_BAD_INPUT"
    assert fal.count("submit") == 0 and fal.count("upload") == 0 and hits(board) == 0


def test_video_needs_a_prompt(client: TestClient, board: str, fal: MockFal) -> None:
    _src, node = start(client, board)
    client.patch(f"/api/nodes/{node}", json={"params": {"prompt": "  "}})
    run = run_node(client, node)
    assert run["error_code"] == "PLUGIN_BAD_INPUT" and fal.count("submit") == 0


def test_video_creates_video_item_with_frames(
    client: TestClient, board: str, db: Session, fal: MockFal
) -> None:
    src, node = start(client, board)
    run = run_node(client, node)
    assert run["status"] == "done", (run["error_code"], run["error_message"])
    (vid,) = run["output"]["created_item_ids"]
    db.expire_all()
    item = db.get(BoardItem, vid)
    assert item is not None
    assert item.kind == "video" and item.origin == "generated" and item.parent_item_id == src
    assert item.rights_status == "generated" and item.option_run_id is None
    assert item.storage_path and item.storage_path.endswith(".mp4")
    from app.db.repos import items as items_repo

    assert items_repo.frames(db, vid)
    assert client.get(f"/api/items/{vid}/image").status_code == 200
    assert hits(board) == 1 and fal.count("download") == 1


def test_video_over_size_cap_fails_and_refunds(
    client: TestClient, board: str, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_VIDEO_BYTES", "8")
    _, node = start(client, board)
    run = run_node(client, node)
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_BAD_OUTPUT"
    assert hits(board) == 0 and fal.count("submit") == 1


def test_video_not_connected_without_key(
    client: TestClient, board: str, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, node = start(client, board)
    monkeypatch.delenv("FAL_KEY")
    r = client.post(f"/api/nodes/{node}/run")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PLUGIN_NOT_CONNECTED"


def test_raw_bytes_for_video_only_from_model_runner() -> None:
    from app.plugins.manifest import Manifest
    from app.plugins.runners import PluginError, validate_output

    base = {"id": "xx", "runs_on": "Python", "name": "X", "description": "d", "mark": "X", "tint": "#fff",
            "ink": "#000", "outputs": ["video"], "inputs": {"kinds": ["image"]}}  # fmt: skip
    py = Manifest.model_validate({**base, "runner": "python", "entry": "main.py"})
    with pytest.raises(PluginError):
        validate_output(py, {"video": [{"data": b"x", "caption": ""}]})
