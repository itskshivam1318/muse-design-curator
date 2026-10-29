"""Palette & material: colours for the group (one note) and for each image (an attribute)."""

import numpy as np
from palette_core import load_rgb, palette, sample_pixels


def _hexes(pal):
    return ", ".join(p["hex"] for p in pal)


def run(inputs, params, ctx):
    k = int(params.get("count", 5))
    pooled, attributes = [], []
    for item in inputs:
        if not item.get("image_path"):
            continue
        rgb = load_rgb(item["image_path"])
        pooled.append(sample_pixels(rgb, 20_000 // max(1, len(inputs))))
        attributes.append(
            {
                "item_id": item["id"],
                "key": "palette",
                "label": "Palette",
                "value": _hexes(palette(rgb, k)),
            }
        )
    if not pooled:
        return {"notes": [], "attributes": []}
    group = palette(np.concatenate(pooled), k)
    return {"notes": [{"text": f"Palette: {_hexes(group)}"}], "attributes": attributes}
