"""Image / text embedders. Torch-based ones are lazy so the module imports without the extra."""

from __future__ import annotations

import hashlib
import io
from typing import Any, Protocol

import numpy as np
from PIL import Image

from app.providers.reliability import ModelError


class Embedder(Protocol):
    id: str
    dim: int

    def embed_images(self, images: list[bytes]) -> np.ndarray: ...

    def embed_text(self, texts: list[str]) -> np.ndarray: ...


def l2_normalise(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norm == 0, 1.0, norm)  # type: ignore[no-any-return]


class MockEmbedder:
    """64-d RGB histogram (4x4x4 bins of a 64x64 downsample), L2-normalised."""

    id = "mock"
    dim = 64

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        rows = []
        for data in images:
            with Image.open(io.BytesIO(data)) as im:
                px = np.asarray(im.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR))
            q = (px // 64).reshape(-1, 3).astype(int)
            idx = q[:, 0] * 16 + q[:, 1] * 4 + q[:, 2]
            rows.append(np.bincount(idx, minlength=64).astype(np.float64))
        return l2_normalise(np.array(rows).reshape(len(rows), 64))

    def embed_text(self, texts: list[str]) -> np.ndarray:
        rows = []
        for t in texts:
            d = hashlib.sha256(t.encode()).digest() * 2
            rows.append(np.frombuffer(d, dtype=np.uint8).astype(np.float64) + 1.0)
        return l2_normalise(np.array(rows).reshape(len(rows), 64))


_EXTRA_HINT = "install the optional extra: `uv sync --extra embed` (torch, transformers)"


def _require_torch(name: str) -> Any:
    try:
        import torch
        import transformers  # noqa: F401
    except ImportError as exc:
        raise ModelError(
            "PROVIDER_MISCONFIGURED",
            message=f"EMBEDDER={name} needs the 'embed' extra; {_EXTRA_HINT}",
        ) from exc
    return torch


class SigLIP2Embedder:
    id = "siglip2"

    def __init__(self, model_name: str = "google/siglip2-base-patch16-256") -> None:
        torch = _require_torch("siglip2")
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        self.model_name = model_name
        self._model = AutoModel.from_pretrained(model_name).eval()
        self._proc = AutoProcessor.from_pretrained(model_name)
        self.dim = int(self._model.config.text_config.hidden_size)

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        pics = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
        inputs = self._proc(images=pics, return_tensors="pt")
        with self._torch.no_grad():
            out = self._model.get_image_features(**inputs)
        return l2_normalise(out.cpu().numpy())

    def embed_text(self, texts: list[str]) -> np.ndarray:
        inputs = self._proc(text=texts, padding="max_length", max_length=64, return_tensors="pt")
        with self._torch.no_grad():
            out = self._model.get_text_features(**inputs)
        return l2_normalise(out.cpu().numpy())


class PECoreEmbedder:
    """Meta Perception Encoder (core) via open_clip. Not exercised in tests (needs weights)."""

    id = "pecore"

    def __init__(self, model_name: str = "hf-hub:timm/PE-Core-B-16") -> None:
        torch = _require_torch("pecore")
        try:
            import open_clip
        except ImportError as exc:
            raise ModelError(
                "PROVIDER_MISCONFIGURED",
                message="EMBEDDER=pecore also needs `open_clip_torch`; " + _EXTRA_HINT,
            ) from exc
        self._torch = torch
        model, _, preprocess = open_clip.create_model_and_transforms(model_name)
        self._model = model.eval()
        self._preprocess = preprocess
        self._tok = open_clip.get_tokenizer(model_name)
        self.dim = int(self._model.visual.output_dim)

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        batch = self._torch.stack(
            [self._preprocess(Image.open(io.BytesIO(b)).convert("RGB")) for b in images]
        )
        with self._torch.no_grad():
            return l2_normalise(self._model.encode_image(batch).cpu().numpy())

    def embed_text(self, texts: list[str]) -> np.ndarray:
        with self._torch.no_grad():
            return l2_normalise(self._model.encode_text(self._tok(texts)).cpu().numpy())
