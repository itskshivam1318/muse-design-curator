"""Image-edit providers: restyle a source image from a text prompt, returning PNG bytes."""

from __future__ import annotations

import base64
import hashlib
import io
from typing import Protocol

import openai
from PIL import Image

from app.providers.meta_client import check_model_id
from app.providers.reliability import ModelError, call_model

MAX_SOURCE_EDGE = 1536


class ImageProvider(Protocol):
    id: str
    model: str
    is_mock: bool

    def edit(self, image: bytes, prompt: str) -> bytes: ...


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise ModelError("MODEL_INVALID_RESPONSE", message=f"unreadable image: {exc}") from exc
    return img


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


class MuseImageProvider:
    id = "muse_image"
    is_mock = False

    def __init__(
        self, client: openai.OpenAI, model: str, *, max_retries: int = 2, timeout: float = 120
    ) -> None:
        self.client = client
        self.model = check_model_id(model)
        self.max_retries = max_retries
        self.timeout = timeout

    def edit(self, image: bytes, prompt: str) -> bytes:
        src = _open(image).convert("RGB")
        if max(src.size) > MAX_SOURCE_EDGE:
            src.thumbnail((MAX_SOURCE_EDGE, MAX_SOURCE_EDGE), Image.Resampling.LANCZOS)
        png = _to_png(src)

        def go() -> bytes:
            resp = self.client.images.edit(
                model=self.model, image=("source.png", png, "image/png"), prompt=prompt
            )
            b64 = resp.data[0].b64_json if resp.data else None
            if not b64:
                raise ModelError("MODEL_INVALID_RESPONSE", message="no image in edit response")
            return base64.b64decode(b64)

        raw = call_model(go, timeout=self.timeout, max_retries=self.max_retries)
        return _to_png(_open(raw))


class MockImageProvider:
    """Deterministic: the source blended 20% towards a colour derived from the prompt."""

    id = "mock"
    model = "mock-image"
    is_mock = True

    def edit(self, image: bytes, prompt: str) -> bytes:
        src = _open(image).convert("RGB")
        d = hashlib.sha256(prompt.encode()).digest()
        tint = Image.new("RGB", src.size, (d[0], d[1], d[2]))
        return _to_png(Image.blend(src, tint, 0.2))
