"""Content hashes for corpus images. The dHash algorithm lives in `app.imaging`."""

import hashlib
import io

from PIL import Image

from app import imaging


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dhash(data: bytes) -> str:
    """64-bit difference hash of encoded image bytes, as 16 lowercase hex digits."""
    with Image.open(io.BytesIO(data)) as img:
        return f"{imaging.dhash(img):016x}"


def hamming(a: str, b: str) -> int:
    return imaging.hamming(int(a, 16), int(b, 16))
