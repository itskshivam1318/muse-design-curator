"""Cut an object out of a picture. Pure numpy / Pillow: the plugin shim imports this folder in
isolation, so nothing from `app` may be imported here."""

from typing import Literal

import numpy as np
from PIL import Image


def cutout(
    image: Image.Image,
    mask: np.ndarray | None,
    box: tuple[int, int, int, int] | None,
    background: Literal["transparent", "white"] = "transparent",
    margin: float = 0.0,
) -> Image.Image:
    """Crop `image` to `box` (pixels x0, y0, x1, y1), else to the mask's bounding box, grown by
    `margin` of that box on every side and clamped to the picture. `mask` is image-sized, true
    inside (a PNG mask is read with > 127). Outside the mask the result is transparent (RGBA) or
    white (RGB). Raises ValueError when there is nothing to keep."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    keep: np.ndarray | None = None
    if mask is not None:
        keep = np.asarray(mask)
        if keep.dtype != np.bool_:
            keep = keep > 127
        if keep.shape != (height, width):
            raise ValueError("mask and image differ in size")
    if box is not None:
        x0, y0, x1, y1 = box
    elif keep is not None:
        ys, xs = np.nonzero(keep)
        if ys.size == 0:
            raise ValueError("the mask is empty")
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    else:
        x0, y0, x1, y1 = 0, 0, width, height
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, width), min(y1, height)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the box is empty")
    if keep is not None and not keep[y0:y1, x0:x1].any():
        raise ValueError("the mask is empty inside the box")
    if margin > 0:
        mx, my = round((x1 - x0) * margin), round((y1 - y0) * margin)
        x0, y0, x1, y1 = max(x0 - mx, 0), max(y0 - my, 0), min(x1 + mx, width), min(y1 + my, height)
    crop = rgb.crop((x0, y0, x1, y1))
    inside = None if keep is None else keep[y0:y1, x0:x1]
    if background == "white":
        if inside is None:
            return crop
        arr = np.asarray(crop).copy()
        arr[~inside] = 255
        return Image.fromarray(arr, "RGB")
    out = crop.convert("RGBA")
    if inside is not None:
        out.putalpha(Image.fromarray(inside.astype(np.uint8) * 255, "L"))
    return out
