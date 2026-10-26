import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.config import Settings
from app.providers.meta_client import get_client
from app.providers.segmentation import Sam31Provider
from tests.unit.providers.fake_http import FakeApi, response

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "meta"
URL = "https://api.meta.ai/v1/responses"


def png(w: int = 100, h: int = 80) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, "PNG")
    return buf.getvalue()


def sse(name: str):  # type: ignore[no-untyped-def]
    return response(
        200, headers={"content-type": "text/event-stream"}, text=(FIX / name).read_text()
    )


def provider(api: FakeApi) -> Sam31Provider:
    client = get_client(Settings(MODEL_API_KEY="k"), http_client=api.http)
    return Sam31Provider(client, timeout=5, max_retries=0)


def test_sam_fixture_decodes_to_instance_inside_bounds(api: FakeApi) -> None:
    route = api.post(URL, sse("sam_image.sse"))
    res = provider(api).localize(png(100, 80), "sha", "watch dial")
    assert res.found and len(res.instances) >= 1
    inst = res.instances[0]
    x1, y1, x2, y2 = inst.bbox
    assert 0 <= x1 < x2 <= 100 and 0 <= y1 < y2 <= 80
    assert inst.mask.dtype == bool and inst.mask.shape == (80, 100)
    assert inst.mask.any()
    ys, xs = np.nonzero(inst.mask)
    assert xs.min() >= x1 and xs.max() < x2 and ys.min() >= y1 and ys.max() < y2
    assert inst.score == pytest.approx(0.88)
    body = json.loads(route.last.content)
    assert body["model"] == "sam-3.1" and body["stream"] is True
    assert body["metadata"] == {"include_confidence": "true", "mask_encoding": "one_bit"}
    parts = body["input"][0]["content"]
    assert parts[0] == {"type": "input_text", "text": "watch dial"}
    assert parts[1]["type"] == "input_image"


def test_empty_sam_output_is_not_found(api: FakeApi) -> None:
    api.post(URL, sse("sam_empty.sse"))
    res = provider(api).localize(png(), "sha", "nothing")
    assert res.found is False and res.instances == []
