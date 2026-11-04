"""Clean-up: each picture cut out along its object mask, on transparent or white."""

import os

import numpy as np
from cutout import cutout
from PIL import Image

MARGIN = 0.04


def run(inputs, params, ctx):
    background = params.get("background", "transparent")
    if background not in ("transparent", "white"):
        return {"error": "background must be transparent or white"}
    images = []
    for n, item in enumerate(inputs):
        path, mask_path = item.get("image_path"), item.get("object_mask_path")
        if not path or not mask_path:
            continue
        with Image.open(path) as im, Image.open(mask_path) as m:
            rgb = im.convert("RGB")
            mask = np.asarray(m.convert("L").resize(rgb.size, Image.Resampling.NEAREST)) > 127
        try:
            out = cutout(rgb, mask, None, background, MARGIN)
        except ValueError:
            return {"error": f"Nothing found to cut out of {item.get('label') or 'a picture'}"}
        name = f"cleanup-{n}.png"
        out.save(os.path.join(os.getcwd(), name), "PNG")
        images.append({"path": name, "caption": f"{item.get('label') or 'Picture'}, cleaned up"})
    return {"images": images}
