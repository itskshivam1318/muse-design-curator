"""Image → 3D: a cleaned cut-out goes to fal, the .glb comes back as a model item."""

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app import demo
from app.config import get_settings
from app.db.models import BoardItem
from app.explore.visualize import _iso
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


def hits(board: str) -> int:
    return len(demo.windows._hits.get(f"mesh:{board}", ()))


def test_mesh_resumed_download_failure_keeps_other_slots(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import PluginRun
    from app.plugins import runners

    monkeypatch.setattr(runners, "MAX_GLB_BYTES", 8)
    _, node = start(client, board, db)
    monkeypatch.setattr("app.jobs.enqueue", lambda *_a, **_k: None)
    rid = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    run = db.get(PluginRun, rid)
    assert run is not None
    ep = get_settings().FAL_MESH_FAST
    run.external_json = {"endpoint": ep, "request_id": "mock-old", "status": "IN_QUEUE",
                         "cap": "mesh", "submitted_at": _iso(datetime.now(UTC))}  # fmt: skip
    db.commit()
    demo.windows._hits.pop(f"mesh:{board}", None)
    from app.analysis import limits

    limits.check_and_count(board, "mesh", get_settings())  # another run's hit
    from app.plugins import service

    service.execute_run(db, rid)
    db.expire_all()
    done = db.get(PluginRun, rid)
    assert done is not None and done.status == "failed"
    assert done.error_code == "PLUGIN_BAD_OUTPUT", done.error_code
    assert fal.count("download") == 1
    assert fal.count("submit") == 0 and hits(board) == 1


@pytest.mark.parametrize("case", ["no_url", "empty"])
def test_mesh_missing_url_and_empty_glb_refund(
    client: TestClient, board: str, db: Session, fal: MockFal, case: str
) -> None:
    ep = get_settings().FAL_MESH_FAST
    if case == "no_url":
        fal.results[ep] = {"seed": 1}
    else:
        fal.files[GLB_URL] = b""
    _, node = start(client, board, db)
    run = run_node(client, node["id"])
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_BAD_OUTPUT"
    assert hits(board) == 0


def run_with_old_request(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch, resumed: bool
) -> Any:
    """A mesh run whose fal result is fine but whose writeback fails (the poster is garbage)."""
    from app.db.models import PluginRun
    from app.plugins import service

    _, node = start(client, board, db)
    monkeypatch.setattr("app.jobs.enqueue", lambda *_a, **_k: None)
    rid = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    run = db.get(PluginRun, rid)
    assert run is not None
    if resumed:
        run.status = "running"
        run.external_json = {"endpoint": get_settings().FAL_MESH_FAST, "request_id": "mock-old",
                             "status": "IN_QUEUE", "cap": "mesh",
                             "submitted_at": _iso(datetime.now(UTC))}  # fmt: skip
        db.commit()
        demo.windows._hits.pop(f"mesh:{board}", None)
        from app.analysis import limits

        limits.check_and_count(board, "mesh", get_settings())  # the submitting process's slot
    monkeypatch.setattr(
        "app.plugins.writeback._model_item",
        lambda *_a, **_k: (_ for _ in ()).throw(
            __import__("app.plugins.runners", fromlist=["PluginError"]).PluginError(
                "PLUGIN_BAD_OUTPUT", "poster"
            )
        ),
    )
    service.execute_run(db, rid) if not resumed else service.resume_run(db, rid)
    db.expire_all()
    done = db.get(PluginRun, rid)
    assert done is not None and done.status == "failed"
    return done


def test_fresh_run_writeback_failure_refunds_the_slot(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_with_old_request(client, board, db, monkeypatch, resumed=False)
    assert hits(board) == 0


def test_resumed_run_writeback_failure_keeps_the_slot(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_with_old_request(client, board, db, monkeypatch, resumed=True)
    assert hits(board) == 1


def test_mesh_superseded_while_running_refunds(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import PluginRun
    from app.plugins import service

    _, node = start(client, board, db)
    monkeypatch.setattr("app.jobs.enqueue", lambda *_a, **_k: None)
    rid = client.post(f"/api/nodes/{node['id']}/run").json()["id"]
    real = fal.result

    def result_then_supersede(endpoint: str, request_id: str) -> dict[str, Any]:
        out = real(endpoint, request_id)
        db.query(PluginRun).filter(PluginRun.id == rid).update({"status": "failed"})
        db.commit()
        return out

    monkeypatch.setattr(fal, "result", result_then_supersede)
    service.execute_run(db, rid)
    assert hits(board) == 0


def test_mesh_rejects_non_glb_bytes_and_refunds(
    client: TestClient, board: str, db: Session, fal: MockFal
) -> None:
    fal.files[GLB_URL] = b"<html>not a model</html>"
    _, node = start(client, board, db)
    run = run_node(client, node["id"])
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_BAD_OUTPUT"
    assert hits(board) == 0


def test_mesh_unexpected_download_exception_refunds(
    client: TestClient, board: str, db: Session, fal: MockFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(url: str, max_bytes: int) -> bytes:
        raise OSError("socket closed")

    monkeypatch.setattr(fal, "download", boom)
    _, node = start(client, board, db)
    run = run_node(client, node["id"])
    assert run["status"] == "failed" and run["error_code"] == "PLUGIN_MODEL_FAILED"
    assert hits(board) == 0
