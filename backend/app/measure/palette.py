"""Colour measurement: k-means palettes in CIELAB, CIEDE2000, named colours."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, lab2rgb, rgb2lab
from sklearn.cluster import KMeans

MAX_PIXELS = 20_000
MERGE_DELTA_E = 8.0

# name -> sRGB
COLOR_TABLE: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "charcoal": (54, 69, 79),
    "navy": (0, 0, 128),
    "blue": (0, 0, 255),
    "royal_blue": (65, 105, 225),
    "teal": (0, 128, 128),
    "green": (0, 160, 0),
    "olive": (128, 128, 0),
    "sage": (156, 175, 136),
    "yellow": (255, 255, 0),
    "mustard": (225, 173, 1),
    "orange": (255, 140, 0),
    "rust": (183, 65, 14),
    "red": (255, 0, 0),
    "burgundy": (128, 0, 32),
    "pink": (255, 105, 180),
    "blush": (222, 93, 131),
    "purple": (128, 0, 128),
    "lavender": (181, 126, 220),
    "brown": (101, 67, 33),
    "tan": (210, 180, 140),
    "beige": (245, 245, 220),
    "cream": (255, 253, 208),
    "champagne": (247, 231, 206),
    "gold": (212, 175, 55),
    "salmon": (250, 128, 114),
    "khaki": (195, 176, 145),
}

Lab = tuple[float, float, float]


def to_rgb_array(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes to an HxWx3 uint8 RGB array (first frame)."""
    with Image.open(io.BytesIO(image_bytes)) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    px = np.asarray(rgb, dtype=np.uint8).reshape(-1, 1, 3)
    return rgb2lab(px).reshape(-1, 3)


def _lab_to_hex(lab: np.ndarray) -> str:
    rgb = lab2rgb(np.asarray(lab, dtype=float).reshape(1, 1, 3)).reshape(3)
    r, g, b = (round(float(np.clip(v, 0, 1)) * 255) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _pixels(image: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    pix = image[mask] if mask is not None else image.reshape(-1, 3)
    return np.asarray(pix, dtype=np.uint8).reshape(-1, 3)


def masked_palette(image: np.ndarray, mask: np.ndarray | None, k: int = 5) -> list[dict[str, Any]]:
    """K-means palette in Lab over masked pixels; sorted by share descending."""
    pix = _pixels(image, mask)
    if len(pix) == 0:
        return []
    rng = np.random.default_rng(0)
    if len(pix) > MAX_PIXELS:
        pix = pix[rng.choice(len(pix), MAX_PIXELS, replace=False)]
    uniq = np.unique(pix, axis=0)
    lab = _rgb_to_lab(pix)
    n = max(1, min(k, len(uniq)))
    km = KMeans(n_clusters=n, n_init=4, random_state=0).fit(lab)
    counts = np.bincount(km.labels_, minlength=n)
    out: list[dict[str, Any]] = []
    for i in np.argsort(-counts, kind="stable"):
        if counts[i] == 0:
            continue
        c = km.cluster_centers_[i]
        out.append(
            {
                "lab": (round(float(c[0]), 4), round(float(c[1]), 4), round(float(c[2]), 4)),
                "hex": _lab_to_hex(c),
                "share": float(counts[i] / counts.sum()),
            }
        )
    return out


def dominant_lab(palette: list[dict[str, Any]]) -> Lab:
    return palette[0]["lab"]


def delta_e(a: Lab, b: Lab) -> float:
    """CIEDE2000 between two Lab colours."""
    return float(deltaE_ciede2000(np.asarray(a, dtype=float), np.asarray(b, dtype=float)))


def _named_labs() -> dict[str, Lab]:
    names = list(COLOR_TABLE)
    labs = _rgb_to_lab(np.array([COLOR_TABLE[n] for n in names], dtype=np.uint8))
    return {n: (float(r[0]), float(r[1]), float(r[2])) for n, r in zip(names, labs, strict=True)}


_NAMED_LAB = _named_labs()


def nearest_color_name(lab: Lab) -> str:
    return min(_NAMED_LAB, key=lambda n: delta_e(lab, _NAMED_LAB[n]))


def palette_count(image: np.ndarray, mask: np.ndarray | None, min_share: float = 0.05) -> int:
    """Number of distinct colours (k<=8) with share >= min_share after merging close clusters."""
    pal = masked_palette(image, mask, k=8)
    merged: list[dict[str, Any]] = []
    for p in pal:  # descending share: small clusters merge into larger ones
        for m in merged:
            if delta_e(p["lab"], m["lab"]) < MERGE_DELTA_E:
                m["share"] += p["share"]
                break
        else:
            merged.append({"lab": p["lab"], "share": p["share"]})
    return sum(1 for m in merged if m["share"] >= min_share)


def mask_ratio(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Area of mask_a relative to mask_b (0.0 when mask_b is empty)."""
    b = int(np.count_nonzero(mask_b))
    return float(np.count_nonzero(mask_a) / b) if b else 0.0


def color_names() -> set[str]:
    """The named colours a colour attribute can take."""
    return set(_NAMED_LAB)


def named_lab(name: str) -> Lab | None:
    """Lab of a named colour, or None when the name is unknown."""
    return _NAMED_LAB.get(name)
