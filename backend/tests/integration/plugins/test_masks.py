"""Host-prepared masks for python plugins: metering and the files a plugin sees."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import demo
from app.analysis import locate as locate_mod
from app.db.models import BoardItem, ItemPart, PluginRun
from app.plugins import service
from app.plugins.manifest import load_manifest
from app.plugins.masks import prepare_masks
from app.plugins.registry import Plugin
from app.plugins.runners import BoardCtx, run_plugin
from app.providers.segmentation import MockSegmentationProvider, SegResult
from tests.integration.api.test_nodes_api import upload_image


class CountingSeg(MockSegmentationProvider):
    def __init__(self) -> None:
        self.calls = 0

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        self.calls += 1
        return super().localize(image, sha256, noun)


class FailingSeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        from app.providers.reliability import ModelError

        raise ModelError("boom")


KEYS = ["body", "detail", "seat", "leg"]


def slots(board: str) -> int:
    return len(demo.windows._hits.get(f"analyse:{board}", ()))


def item_with_parts(client: TestClient, board: str, db: Session) -> BoardItem:
    item_id = upload_image(client, board)
    for key in ("seat", "leg"):
        db.add(ItemPart(item_id=item_id, key=key, label=key.title(), region_kind="mask",
                        source="ai"))  # fmt: skip
    item = db.get(BoardItem, item_id)
    assert item is not None
    item.subject = "lounge chair"
    db.commit()
    return item


def test_prepare_masks_counts_once_and_refunds(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = item_with_parts(client, board, db)
    before = slots(board)
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: FailingSeg())
    with pytest.raises(Exception, match="locate"):
        prepare_masks(db, board, item, ["parts"])
    assert slots(board) == before  # refunded

    seg = CountingSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    out = prepare_masks(db, board, item, ["parts", "object_mask"])
    assert slots(board) == before + 1  # two parts and the object, one slot
    assert [k for k, _, _ in out["parts"]] == KEYS
    assert out["object"] is not None and out["object"].shape == out["parts"][0][2].shape

    calls = seg.calls
    prepare_masks(db, board, item, ["parts", "object_mask"])
    assert slots(board) == before + 1 and seg.calls == calls  # fully cached: free


def test_python_payload_has_mask_paths(
    client: TestClient, board: str, db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: MockSegmentationProvider())
    item = item_with_parts(client, board, db)
    d = tmp_path / "echo"
    d.mkdir()
    (d / "main.py").write_text(
        "import json, os\n"
        "def run(inputs, params, ctx):\n"
        "    i = inputs[0]\n"
        "    paths = [x['mask_path'] for x in i['parts']] + [i['object_mask_path']]\n"
        "    run_dir = os.path.dirname(os.path.dirname(i['image_path']))\n"
        "    checks = [[os.path.isfile(p), os.access(p, os.W_OK), os.path.dirname(os.path.dirname(p)) == run_dir, os.path.basename(p)] for p in paths]\n"
        "    return {'text': json.dumps({'input': i, 'checks': checks})}\n"
    )
    (d / "plugin.json").write_text(json.dumps({
        "id": "echo", "name": "Echo", "description": "x", "mark": "E", "tint": "#fff",
        "ink": "#000", "runner": "python", "runs_on": "Python",
        "inputs": {"kinds": ["image"]}, "outputs": ["text"], "entry": "main.py",
        "needs": ["parts", "object_mask"],
    }))  # fmt: skip
    p = Plugin(load_manifest(d, builtin=False), d, False)
    run = PluginRun(board_id=board, node_id="n", plugin_id="echo", input_item_ids_json=[item.id],
                    params_json={}, status="running")  # fmt: skip
    inputs = service._inputs(db, run, p)
    out = run_plugin(p, inputs, {}, BoardCtx(title="", context=None, notes=[]), lambda _m: None)
    got = json.loads(out["text"])
    assert [x["key"] for x in got["input"]["parts"]] == KEYS
    assert len(got["checks"]) == len(KEYS) + 1
    for exists, writable, inside, name in got["checks"]:
        assert exists and not writable and inside
        assert "-part-" in name or name.endswith("-object.png")


class EmptySeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        self.calls = getattr(self, "calls", 0) + 1
        return SegResult(False, [])


def test_nothing_found_refunds_and_object_need_raises(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.errors import AppError

    item = item_with_parts(client, board, db)
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())
    before = slots(board)
    with pytest.raises(AppError) as e:
        prepare_masks(db, board, item, ["object_mask"])
    assert (e.value.status, e.value.code) == (422, "REGION_EMPTY")
    assert slots(board) == before
    # parts only: nothing located is an empty result, also refunded
    out = prepare_masks(db, board, item, ["parts"])
    assert out["parts"] == [] and slots(board) == before


def test_cached_not_found_part_takes_no_slot(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = item_with_parts(client, board, db)
    seg = EmptySeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    prepare_masks(db, board, item, ["parts"])  # SAM finds nothing; the not-found rows are cached
    calls, before = seg.calls, slots(board)
    prepare_masks(db, board, item, ["parts"])
    assert seg.calls == calls and slots(board) == before
