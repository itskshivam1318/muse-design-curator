from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from app.config import Settings
from app.providers import ModelError, get_image_provider
from app.providers.image_gen import MockImageProvider, MuseImageProvider
from app.providers.meta_client import get_client
from tests.unit.providers.fake_http import FakeApi, response

BASE = "https://api.meta.ai/v1"


def _png(size: tuple[int, int] = (64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buf, "PNG")
    return buf.getvalue()


def _webp_b64(size: tuple[int, int] = (32, 32)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 90, 200)).save(buf, "WEBP")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def _provider(api: FakeApi) -> MuseImageProvider:
    client = get_client(Settings(MODEL_API_KEY="k"), http_client=api.http)
    return MuseImageProvider(client, "muse-image-1.0", max_retries=0, timeout=5)


def test_mock_edit_is_deterministic_png() -> None:
    src = _png()
    p = MockImageProvider()
    a, b = p.edit(src, "make it blue"), p.edit(src, "make it blue")
    assert a == b and a != src
    assert Image.open(io.BytesIO(a)).size == (64, 48)
    assert p.is_mock and p.id == "mock" and p.model == "mock-image"


def test_muse_image_posts_multipart_edit(api: FakeApi) -> None:
    route = api.post(
        f"{BASE}/images/edits",
        response(json={"created": 1, "data": [{"b64_json": _webp_b64()}], "output_format": "webp"}),
    )
    out = _provider(api).edit(_png(), "a calmer palette")
    assert out.startswith(b"\x89PNG")
    req = route.last
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="model"' in body and b"muse-image-1.0" in body
    assert b'name="prompt"' in body and b"a calmer palette" in body
    assert b'name="image"' in body


def test_muse_image_shrinks_large_source(api: FakeApi) -> None:
    route = api.post(f"{BASE}/images/edits", response(json={"data": [{"b64_json": _webp_b64()}]}))
    _provider(api).edit(_png((4000, 3000)), "x")
    body = route.last.content
    start = body.index(b"\x89PNG")
    sent = Image.open(io.BytesIO(body[start:]))
    assert max(sent.size) <= 1536


def test_get_image_provider_unknown_raises() -> None:
    with pytest.raises(ModelError) as e:
        get_image_provider(Settings(IMAGE_PROVIDER="nope"))
    assert e.value.code == "PROVIDER_MISCONFIGURED"


def test_get_image_provider_needs_key() -> None:
    with pytest.raises(ModelError) as e:
        get_image_provider(Settings(IMAGE_PROVIDER="muse-image", MODEL_API_KEY=None))
    assert e.value.code == "PROVIDER_MISCONFIGURED"
    assert isinstance(get_image_provider(Settings(IMAGE_PROVIDER="mock")), MockImageProvider)
    p = get_image_provider(Settings(IMAGE_PROVIDER="muse-image", MODEL_API_KEY="k"))
    assert isinstance(p, MuseImageProvider)


def test_mock_generate_deterministic() -> None:
    p = MockImageProvider()
    a, b = p.generate("a honey jar"), p.generate("a honey jar")
    assert a == b and a != p.generate("a steel kettle")
    img = Image.open(io.BytesIO(a))
    assert img.format == "PNG" and img.size == (768, 768)


def test_muse_generate_request_shape(api: FakeApi) -> None:
    import json

    route = api.post(
        f"{BASE}/images/generations", response(json={"data": [{"b64_json": _webp_b64()}]})
    )
    out = _provider(api).generate("a honey jar")
    assert out.startswith(b"\x89PNG")
    assert json.loads(route.last.content) == {"model": "muse-image-1.0", "prompt": "a honey jar"}
