"""Variation · Color end to end: an analysed item's mask parts, recoloured into an option grid
with no model calls."""

import base64
import io
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import locate as locate_mod
from app.db.models import BoardItem, ItemPart, PluginRun
from app.plugins import service
from app.plugins.manifest import load_manifest
from app.plugins.registry import BUILTIN_DIR, Plugin, load_builtin_module
from app.plugins.runners import BoardCtx, PluginError, check_params, run_plugin
from app.providers.image_gen import MockImageProvider
from app.providers.reasoning import MockReasoningProvider
from app.providers.segmentation import MockSegmentationProvider, SegInstance, SegResult
from tests.integration.api.test_nodes_api import add_plugin, make_node, run_node, upload_image

rc = load_builtin_module("recolor", "recolor")


class BandSeg(MockSegmentationProvider):
    """Each new part noun gets the next horizontal band of the middle of the picture, so the
    parts are distinct and neighbouring bands touch."""

    def __init__(self) -> None:
        self.nouns: list[str] = []

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        if noun not in self.nouns:
            self.nouns.append(noun)
        k = self.nouns.index(noun)
        with Image.open(io.BytesIO(image)) as im:
            w, h = im.size
        y1, y2 = int(h * (0.1 + 0.2 * k)), int(h * (0.3 + 0.2 * k))
        x1, x2 = int(w * 0.1), int(w * 0.9)
        mask = np.zeros((h, w), bool)
        mask[y1:y2, x1:x2] = True
        return SegResult(True, [SegInstance((x1, y1, x2, y2), mask, None)])


@pytest.fixture
def model_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Counts every call into the mock image and reasoning providers."""
    calls = {"image": 0, "reasoning": 0}

    def counted(kind: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*a: Any, **k: Any) -> Any:
            calls[kind] += 1
            return fn(*a, **k)

        return wrapper

    for kind, cls in (("image", MockImageProvider), ("reasoning", MockReasoningProvider)):
        for name in dir(cls):
            attr = getattr(cls, name)
            if not name.startswith("_") and callable(attr):
                monkeypatch.setattr(cls, name, counted(kind, attr))
    return calls


def mask_parts(db: Session, item_id: str) -> list[ItemPart]:
    return [
        p
        for p in db.scalars(select(ItemPart).where(ItemPart.item_id == item_id))
        if not p.removed and p.region_kind in ("mask", "box")
    ]


def shoe(client: TestClient, board: str, db: Session, keys: tuple[str, ...]) -> str:
    """An image item whose live parts are exactly `keys` (mask parts)."""
    item_id = upload_image(client, board)
    for p in mask_parts(db, item_id):
        p.removed = True
    for key in keys:
        db.add(ItemPart(item_id=item_id, key=key, label=key.title(), region_kind="mask",
                        source="ai"))  # fmt: skip
    item = db.get(BoardItem, item_id)
    assert item is not None
    item.subject = "sneaker"
    db.commit()
    return item_id


def test_recolor_plugin_24_options_zero_model_calls(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch,
    model_calls: dict[str, int],
) -> None:  # fmt: skip
    seg = BandSeg()  # one instance: it remembers which band each noun got
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    item_id = shoe(client, board, db, ("upper", "midsole", "outsole"))
    model_calls.update(image=0, reasoning=0)  # analysing the upload is not the plugin's
    d = BUILTIN_DIR / "recolor"
    p = Plugin(load_manifest(d, builtin=True), d, True)
    pr = PluginRun(board_id=board, node_id="n", plugin_id="recolor", input_item_ids_json=[item_id],
                   params_json={}, status="running")  # fmt: skip
    inputs = service._inputs(db, pr, p)  # SAM once per part, then cached
    assert [k for k, _, _ in inputs[0].parts or []] == ["upper", "midsole", "outsole"]

    def run(params: dict[str, Any]) -> list[str]:
        out = run_plugin(p, inputs, check_params(p.manifest, params), BoardCtx("", None, []),
                         lambda _m: None)  # fmt: skip
        return [x["caption"] for x in out["images"]]

    grid = run({"count": 24})
    assert len(grid) == 24 and len(set(grid)) == 24
    assert all(c.startswith("Coral Bay · upper #") for c in grid)
    # the same item + palette + seed + count gives the same grid; a new seed a different one
    assert run({"count": 4, "seed": 1}) == grid[:4] != run({"count": 4, "seed": 2})
    seg_calls = len(seg.nouns)
    service._inputs(db, pr, p)
    assert len(seg.nouns) == seg_calls  # masks cached: nothing new located
    assert model_calls == {"image": 0, "reasoning": 0}

    # through the node: 24 options laid out as a grid
    add_plugin(client, board, "recolor")
    node = make_node(client, board, "recolor", [item_id])
    assert node["params"]["palette"]["name"] == "Coral Bay"
    client.patch(f"/api/nodes/{node['id']}", json={"params": {**node["params"], "count": 24}})
    done = run_node(client, node["id"])
    assert done["status"] == "done", (done["error_code"], done["error_message"])
    ids = done["output"]["created_item_ids"]
    assert len(ids) == 24 and done["output"]["option_item_ids"] == ids
    items = [db.get(BoardItem, i) for i in ids]
    assert all(it is not None and it.option_run_id == done["id"] for it in items)
    assert model_calls["image"] == 0


def test_recolor_plugin_one_part_fails_clearly(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch,
    model_calls: dict[str, int],
) -> None:  # fmt: skip
    seg = BandSeg()  # one instance: it remembers which band each noun got
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    item_id = shoe(client, board, db, ("upper",))
    add_plugin(client, board, "recolor")
    model_calls.update(image=0, reasoning=0)
    run = run_node(client, make_node(client, board, "recolor", [item_id])["id"])
    assert run["status"] == "failed", run
    assert run["error_code"] == "PLUGIN_BAD_INPUT"
    assert run["error_message"] == "This item needs at least two parts to recolour"
    assert model_calls == {"image": 0, "reasoning": 0}


def test_recolor_plugin_parts_all_on_one_region_fail_clearly(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two parts SAM put on the same pixels leave one region: not enough to recolour."""
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: MockSegmentationProvider())
    item_id = shoe(client, board, db, ("upper", "midsole"))
    d = BUILTIN_DIR / "recolor"
    p = Plugin(load_manifest(d, builtin=True), d, True)
    pr = PluginRun(board_id=board, node_id="n", plugin_id="recolor", input_item_ids_json=[item_id],
                   params_json={}, status="running")  # fmt: skip
    with pytest.raises(PluginError) as e:
        run_plugin(p, service._inputs(db, pr, p), {}, BoardCtx("", None, []), lambda _m: None)
    assert e.value.code == "PLUGIN_BAD_INPUT" and "two parts" in e.value.message


def test_recolor_manual_mode_uses_part_colors(
    client: TestClient, board: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seg = BandSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    item_id = shoe(client, board, db, ("upper", "midsole", "outsole"))
    d = BUILTIN_DIR / "recolor"
    p = Plugin(load_manifest(d, builtin=True), d, True)
    pr = PluginRun(board_id=board, node_id="n", plugin_id="recolor", input_item_ids_json=[item_id],
                   params_json={}, status="running")  # fmt: skip
    inputs = service._inputs(db, pr, p)
    params = {"mode": "manual", "part_colors": {"midsole": "#2a9d8f"}}
    out = run_plugin(p, inputs, params, BoardCtx("", None, []), lambda _m: None)
    (image,) = out["images"]
    assert "midsole #2a9d8f" in image["caption"]
    with Image.open(io.BytesIO(base64.b64decode(image["data_b64"]))) as im:
        got = np.asarray(im.convert("RGB"))
    with Image.open(io.BytesIO(inputs[0].image or b"")) as im:
        src = np.asarray(im.convert("RGB"))
    h, w = src.shape[:2]
    # midsole is the second band; keep away from its feathered edges
    inner = (slice(int(h * 0.3) + 4, int(h * 0.5) - 4), slice(int(w * 0.1) + 4, int(w * 0.9) - 4))
    lab = rc.rgb_to_lab(got[inner]).reshape(-1, 3).mean(axis=0)
    target = rc.hex_to_lab("#2a9d8f")
    assert np.hypot(lab[1] - target[1], lab[2] - target[2]) < 8
    # the upper (first band) was not given a colour: untouched
    upper = (slice(int(h * 0.1) + 4, int(h * 0.3) - 4), slice(int(w * 0.1) + 4, int(w * 0.9) - 4))
    assert (got[upper] == src[upper]).all()
