"""Variation · Color: the item's palette-recoloured colourways, part by part. No generation: a CV
pass over the item's SAM part masks, so a run makes no model calls once the masks exist."""

import os

import numpy as np
from PIL import Image
from recolor import (
    Recolorer,
    adjacency,
    assignments,
    label_map,
    norm_hex,
    parse_hex,
    parse_palette,
)

MAX_SIDE = 2048  # long side the work (and the options) are done at
CAPTION_PARTS = 4
TOO_FEW_PARTS = "This item needs at least two parts to recolour"


def _load(item):
    """(rgb, alpha or None, [(key, label, mask)]) at most MAX_SIDE on the long side."""
    with Image.open(item["image_path"]) as im:
        im.load()
        alpha = im.getchannel("A") if "A" in im.getbands() else None
        rgb = im.convert("RGB")
    scale = MAX_SIDE / max(rgb.size)
    if scale < 1:
        size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        rgb = rgb.resize(size, Image.Resampling.LANCZOS)
        alpha = alpha.resize(size, Image.Resampling.LANCZOS) if alpha is not None else None
    parts = []
    for p in item.get("parts") or []:
        with Image.open(p["mask_path"]) as m:
            mask = np.asarray(m.convert("L").resize(rgb.size, Image.Resampling.NEAREST)) > 127
        parts.append((p["key"], p.get("label") or p["key"], mask))
    return np.asarray(rgb, np.uint8), alpha, parts


def _caption(name, labels, colors):
    shown = [f"{labels[i].lower()} {h}" for i, h in sorted(colors.items())]
    more = ", …" if len(shown) > CAPTION_PARTS else ""
    return f"{name} · {', '.join(shown[:CAPTION_PARTS])}{more}"


def _save(rgb, alpha, n):
    im = Image.fromarray(rgb)
    if alpha is not None:
        im.putalpha(alpha)
    name = f"recolor-{n}.png"
    im.save(os.path.join(os.getcwd(), name), "PNG", compress_level=1)
    return name


def run(inputs, params, ctx):
    images = [i for i in inputs if i.get("image_path")]
    if not images:
        return {"error": "Variation needs a picture"}
    item = images[0]
    mode = params.get("mode", "auto")
    try:
        name, palette = parse_palette(params.get("palette"))
    except ValueError as e:
        if mode == "auto":
            return {"error": str(e)}
        name, palette = "Manual", []
    rgb, alpha, parts = _load(item)
    if len(parts) < 2:
        return {"error": TOO_FEW_PARTS}
    labels = label_map([m for _, _, m in parts])
    # a part every pixel of which went to a smaller part has nothing left to colour
    owned = [i for i in range(len(parts)) if (labels == i).any()]
    if len(owned) < 2:
        return {"error": TOO_FEW_PARTS}
    remap = np.full(len(parts) + 1, -1, np.int32)
    remap[owned] = np.arange(len(owned))
    labels = remap[labels]  # -1 indexes the trailing -1
    keys = [parts[i][0] for i in owned]
    names = [parts[i][1] for i in owned]
    painter = Recolorer(rgb, labels)

    if mode == "manual":
        chosen = params.get("part_colors") or {}
        if not isinstance(chosen, dict):
            return {"error": "part_colors must map part keys to colours"}
        colors = {}
        for key, h in chosen.items():
            if key in keys:
                try:
                    parse_hex(h)
                except ValueError:
                    return {"error": f"{h!r} is not a colour"}
                colors[keys.index(key)] = norm_hex(h)
        if not colors:
            return {"error": "Choose a colour for at least one part"}
        path = _save(painter.apply(colors), alpha, 0)
        return {"images": [{"path": path, "caption": _caption("Manual", names, colors)}]}

    count = params.get("count", 8)
    seed = params.get("seed", 1)
    touching = adjacency(labels, len(owned))
    out = []
    for n, a in enumerate(assignments(len(owned), len(palette), touching, count, seed)):
        colors = {i: palette[c] for i, c in enumerate(a)}
        path = _save(painter.apply(colors), alpha, n)
        out.append({"path": path, "caption": _caption(name, names, colors)})
    return {"images": out}
