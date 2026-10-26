"""Content-addressed file storage under DATA_DIR. Originals are written byte-for-byte."""

import hashlib
import io
import os
import tempfile
from pathlib import Path

from PIL import Image

from app.config import data_dir, get_settings

THUMB_MAX = 512


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root() -> Path:
    return data_dir(get_settings())


def abs_path(rel: str) -> Path:
    return root() / rel


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_original(data: bytes, sha: str, ext: str) -> str:
    rel = f"uploads/{sha}.{ext}"
    _write_atomic(abs_path(rel), data)
    return rel


def save_thumb(img: Image.Image, sha: str) -> str:
    rel = f"thumbs/{sha}.webp"
    if not abs_path(rel).exists():
        t = img.copy()
        t.thumbnail((THUMB_MAX, THUMB_MAX))
        t = t.convert("RGBA" if "A" in t.getbands() else "RGB")
        buf = io.BytesIO()
        t.save(buf, "WEBP", quality=82)
        _write_atomic(abs_path(rel), buf.getvalue())
    return rel


def save_frame(img: Image.Image, max_side: int = 1280) -> tuple[str, str]:
    """Store a video frame as JPEG; returns (sha256 of the jpeg bytes, relative path)."""
    f = img.convert("RGB")
    f.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    f.save(buf, "JPEG", quality=90)
    data = buf.getvalue()
    sha = sha256_hex(data)
    rel = f"frames/{sha}.jpg"
    _write_atomic(abs_path(rel), data)
    return sha, rel
