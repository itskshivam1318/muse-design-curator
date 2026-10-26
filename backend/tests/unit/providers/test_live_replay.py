"""Replay real Meta recordings (tests/fixtures/meta/live) through the real providers.

The recordings are written by scripts/smoke_meta.py; tests skip when one is absent.
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings
from app.providers import reliability as rel
from app.providers.meta_client import get_client
from app.providers.reasoning import MuseSparkProvider
from app.providers.segmentation import Sam31Provider
from tests.unit.providers.fake_http import FakeApi, response

LIVE = Path(__file__).resolve().parents[2] / "fixtures" / "meta" / "live"
URL = "https://api.meta.ai/v1/responses"
SCHEMA = {
    "type": "object",
    "properties": {"colors": {"type": "array", "items": {"type": "string"}}},
    "required": ["colors"],
    "additionalProperties": False,
}


def _live(name: str) -> Path:
    p = LIVE / name
    if not p.exists():
        pytest.skip(f"live recording {name} absent; run scripts/smoke_meta.py with a key")
    return p


def _client(api: FakeApi):  # type: ignore[no-untyped-def]
    return get_client(Settings(MODEL_API_KEY="k"), http_client=api.http)


def test_spark_live_schema_recording_parses(api: FakeApi, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rel.time, "sleep", lambda _s: None)
    payload = json.loads(_live("spark_schema.json").read_text())
    assert [o["type"] for o in payload["output"][:2]] == ["reasoning", "message"]
    api.post(URL, response(200, json=payload))
    out = MuseSparkProvider(_client(api), "muse-spark-1.3", max_retries=0, timeout=5).extract(
        [b"\xff\xd8\xff\xe0x"], SCHEMA, "colors"
    )
    assert isinstance(out, dict) and isinstance(out["colors"], list) and out["colors"]


def test_sam_live_image_recording_decodes(api: FakeApi) -> None:
    text = _live("sam_image.txt").read_text()
    lane = {"item_id": "m", "output_index": 0, "content_index": 0}
    evs = [
        {"type": "response.output_text.delta", "delta": text, **lane},
        {"type": "response.output_text.done", "text": text, **lane},
        {"type": "response.completed", "response": {"id": "r"}},
    ]
    sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in evs)
    api.post(URL, response(200, headers={"content-type": "text/event-stream"}, text=sse))
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), (200, 200, 200)).save(buf, "PNG")
    res = Sam31Provider(_client(api), timeout=5, max_retries=0).localize(
        buf.getvalue(), "sha", "watch dial"
    )
    assert res.found and len(res.instances) >= 1
    x1, y1, x2, y2 = res.instances[0].bbox
    assert 0 <= x1 < x2 <= 512 and 0 <= y1 < y2 <= 512
