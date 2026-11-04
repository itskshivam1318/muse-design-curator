import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.analysis import locate as locate_mod
from app.db.models import BoardItem, PluginRun
from app.plugins import service
from app.plugins.manifest import load_manifest
from app.plugins.registry import BUILTIN_DIR, Plugin
from app.plugins.runners import BoardCtx, run_plugin
from app.providers.segmentation import MockSegmentationProvider, SegResult
from tests.integration.api.test_nodes_api import upload_image


class CountingSeg(MockSegmentationProvider):
    def __init__(self) -> None:
        self.calls = 0

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        self.calls += 1
        return super().localize(image, sha256, noun)


def test_cleanup_plugin_makes_one_image_per_input(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seg = CountingSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    ids = []
    for seed in range(2):
        item_id = upload_image(client, board, seed)
        item = db.get(BoardItem, item_id)
        assert item is not None
        item.subject = "lounge chair"
        ids.append(item_id)
    db.commit()
    d = BUILTIN_DIR / "cleanup"
    p = Plugin(load_manifest(d, builtin=True), d, True)
    run = PluginRun(board_id=board, node_id="n", plugin_id="cleanup", input_item_ids_json=ids,
                    params_json={}, status="running")  # fmt: skip
    inputs = service._inputs(db, run, p)
    out = run_plugin(p, inputs, {"background": "white"}, BoardCtx("", None, []), lambda _m: None)
    assert len(out["images"]) == 2
    import base64

    for x in out["images"]:
        with Image.open(io.BytesIO(base64.b64decode(x["data_b64"]))) as im:
            assert im.mode == "RGB"
    assert seg.calls == 2  # segmentation only: one call per picture
