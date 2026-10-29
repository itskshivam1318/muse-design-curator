"""Pure palette functions vendored from app/measure/palette.py (plugins run outside the app, so
they cannot import `app`). K-means in CIELAB, deterministic (fixed seeds)."""

import numpy as np
from PIL import Image
from skimage.color import lab2rgb, rgb2lab
from sklearn.cluster import KMeans

MAX_PIXELS = 20_000


def load_rgb(path):
    """HxWx3 uint8 RGB array of the first frame."""
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def sample_pixels(image, limit=MAX_PIXELS):
    pix = np.asarray(image, dtype=np.uint8).reshape(-1, 3)
    if len(pix) > limit:
        pix = pix[np.random.default_rng(0).choice(len(pix), limit, replace=False)]
    return pix


def _rgb_to_lab(rgb):
    return rgb2lab(np.asarray(rgb, dtype=np.uint8).reshape(-1, 1, 3)).reshape(-1, 3)


def lab_to_hex(lab):
    rgb = lab2rgb(np.asarray(lab, dtype=float).reshape(1, 1, 3)).reshape(3)
    r, g, b = (round(float(np.clip(v, 0, 1)) * 255) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def palette(pixels, k=5):
    """K-means palette in Lab over an Nx3 pixel array; [{hex, share}] by share descending."""
    pix = sample_pixels(pixels)
    if len(pix) == 0:
        return []
    n = max(1, min(k, len(np.unique(pix, axis=0))))
    lab = _rgb_to_lab(pix)
    km = KMeans(n_clusters=n, n_init=4, random_state=0).fit(lab)
    counts = np.bincount(km.labels_, minlength=n)
    out = []
    for i in np.argsort(-counts, kind="stable"):
        if counts[i]:
            out.append(
                {
                    "hex": lab_to_hex(km.cluster_centers_[i]),
                    "share": float(counts[i] / counts.sum()),
                }
            )
    return out
