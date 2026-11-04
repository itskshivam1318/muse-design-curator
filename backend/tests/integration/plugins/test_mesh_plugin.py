"""Image → 3D: a cleaned cut-out goes to fal, the .glb comes back as a model item."""

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app import demo
from app.config import get_settings
from app.db.models import BoardItem
from app.providers import get_fal
from app.providers.fal import MockFal
from tests.integration.api.test_nodes_api import add_plugin, make_node, run_node, upload_image

GLB_URL = "https://v3.fal.media/files/m.glb"
GLB = b"glTF" + b"\x02\x00\x00\x00" + b"mesh-bytes"


@pytest.fixture(autouse=True)
def fal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setenv("FAL_POLL_S", "0")


@pytest.fixture
def fal() -> MockFal:
    mock = get_fal(get_settings())
    assert isinstance(mock, MockFal)
    mock.statuses = ["IN_QUEUE", "COMPLETED"]
    for ep in (get_settings().FAL_MESH_FAST, get_settings().FAL_MESH_DETAILED):
        mock.results[ep] = {"model_mesh": {"url": GLB_URL}, "seed": 1}
    mock.files[GLB_URL] = GLB
    return mock


def start(
    client: TestClient, board: str, db: Session, params: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    add_plugin(client, board, "mesh")
    item_id = upload_image(client, board)
    item = db.get(BoardItem, item_id)
    assert item is not None
    item.subject = "lounge chair"
    db.commit()
    node = make_node(client, board, "mesh", [item_id])
    if params:
        assert client.patch(f"/api/nodes/{node['id']}", json={"params": params}).status_code == 200
    return item_id, node


def test_mesh_uploads_cleaned_cutout(
    client: TestClient, board: str, db: Session, fal: MockFal
) -> None:
    _, node = start(client, board, db)
    run = run_node(client, node["id"])
    assert run["status"] == "done", (run["error_code"], run["error_message"])
    assert fal.count("upload") == 1
    sub = next(c[1] for c in fal.calls if c[0] == "submit")
    url = sub[1]["input_image_url"]
    with Image.open(io.BytesIO(fal.files[url])) as im:
        assert im.mode == "RGBA"
        w, h = im.size
        assert [im.getpixel(p)[3] for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]] == [
            0
        ] * 4


def test_mesh_creates_model_item(client: TestClient, board: str, db: Session, fal: MockFal) -> None:
    src, node = start(client, board, db)
    run = run_node(client, node["id"])
    assert run["status"] == "done", (run["error_code"], run["error_message"])
    (mid,) = run["output"]["created_item_ids"]
    db.expire_all()
    item = db.get(BoardItem, mid)
    assert item is not None
    assert item.kind == "model" and item.origin == "generated" and item.parent_item_id == src
    assert item.rights_status == "generated" and item.mime == "model/gltf-binary"
    assert item.storage_path and item.storage_path.endswith(".glb")
    assert item.thumb_path and item.option_run_id is None
    r = client.get(f"/api/items/{mid}/image", params={"size": "full"})
    assert r.status_code == 200 and r.headers["content-type"] == "model/gltf-binary"
    assert r.content == GLB
    assert client.get(f"/api/items/{mid}/image").status_code == 200  # the poster thumbnail
    assert fal.count("download") == 1


@pytest.mark.parametrize(
    "quality,name", [("fast", "FAL_MESH_FAST"), ("detailed", "FAL_MESH_DETAILED")]
)
def test_mesh_quality_picks_endpoint(
    client: TestClient, board: str, db: Session, fal: MockFal, quality: str, name: str
) -> None:
    _, node = start(client, board, db, {"quality": quality, "texture": False})
    run = run_node(client, node["id"])
    assert run["status"] == "done", (run["error_code"], run["error_message"])
    (call,) = [c[1] for c in fal.calls if c[0] == "submit"]
    assert call[0] == getattr(get_settings(), name)
    assert call[1]["textured_mesh"] is False


def test_mesh_not_connected_without_key(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FAL_KEY")
    _, node = start(client, board, db)
    r = client.post(f"/api/nodes/{node['id']}/run")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PLUGIN_NOT_CONNECTED", r.text
    assert fal.count("submit") == 0
    assert any(
        p["id"] == "mesh" and p["status"] == "not_connected"
        for p in client.get("/api/plugins").json()["plugins"]
    )


def test_mesh_glb_over_50mb_fails_and_refunds(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.plugins import runners

    monkeypatch.setattr(runners, "MAX_GLB_BYTES", 8)  # stand-in for 50 MB
    _, node = start(client, board, db)
    run = run_node(client, node["id"])
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_BAD_OUTPUT"
    assert len(demo.windows._hits.get(f"mesh:{board}", ())) == 0
    assert fal.count("submit") == 1
