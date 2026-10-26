"""Crop a masked part for display or model input."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

GREY = 128


def crop_part(image: np.ndarray, mask: np.ndarray, pad: float = 0.05) -> bytes:
    """PNG of the mask bounding box (padded); pixels outside the mask are 50% grey."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        raise ValueError("empty mask")
    h, w = mask.shape
    py, px = (
        round((ys.max() - ys.min() + 1) * pad),
        round((xs.max() - xs.min() + 1) * pad),
    )
    y0, y1 = max(0, ys.min() - py), min(h, ys.max() + 1 + py)
    x0, x1 = max(0, xs.min() - px), min(w, xs.max() + 1 + px)
    out = np.where(mask[y0:y1, x0:x1, None], image[y0:y1, x0:x1], np.uint8(GREY)).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(out, "RGB").save(buf, "PNG")
    return buf.getvalue()
