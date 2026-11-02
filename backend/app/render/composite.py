"""Put an edited image back into its source only inside a region, with a feathered edge."""

import io

import numpy as np
from PIL import Image, ImageFilter

from app.analysis.types import Region


def _alpha(size: tuple[int, int], region: Region, mask: np.ndarray | None) -> Image.Image:
    """The region as an 8-bit alpha the size of the source: the mask, else the box."""
    width, height = size
    if mask is not None:
        m = Image.fromarray(np.asarray(mask).astype(bool).astype(np.uint8) * 255)
        return m.resize(size, Image.Resampling.NEAREST) if m.size != size else m
    alpha = np.zeros((height, width), dtype=np.uint8)
    if region.box is not None:
        x0, y0, x1, y1 = region.box
        c0, r0 = int(x0 * width), int(y0 * height)
        c1, r1 = int(np.ceil(x1 * width)), int(np.ceil(y1 * height))
        alpha[max(r0, 0) : min(r1, height), max(c0, 0) : min(c1, width)] = 255
    return Image.fromarray(alpha)


def composite_in_region(
    source: bytes, edited: bytes, region: Region, mask: np.ndarray | None, feather_px: int = 6
) -> bytes:
    """`edited`, resized to the source, blended over the source through the region's alpha
    (Gaussian-feathered by `feather_px` inside the region only), as PNG. Every pixel outside
    the region is kept exactly."""
    with Image.open(io.BytesIO(source)) as im:
        im.load()
        has_alpha = "A" in im.getbands() or "transparency" in im.info
        src = im.convert("RGBA")
    with Image.open(io.BytesIO(edited)) as im:
        edit = im.convert("RGBA")
    if edit.size != src.size:
        edit = edit.resize(src.size, Image.Resampling.LANCZOS)
    hard = _alpha(src.size, region, mask)
    a = np.asarray(hard, dtype=np.uint32)
    if feather_px > 0:  # the feather fades in from the edge; it never reaches outside it
        a = np.minimum(np.asarray(hard.filter(ImageFilter.GaussianBlur(feather_px))), a)
    a = a.astype(np.uint32)[..., None]
    s = np.asarray(src, dtype=np.uint32)
    e = np.asarray(edit, dtype=np.uint32)
    blended = (s * (255 - a) + e * a + 127) // 255  # a == 0 gives s exactly
    out = Image.fromarray(blended.astype(np.uint8), "RGBA")
    buf = io.BytesIO()
    (out if has_alpha else out.convert("RGB")).save(buf, "PNG")
    return buf.getvalue()
