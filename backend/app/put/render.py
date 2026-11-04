"""Pure image helpers for "put into": paste a source picture into spots on a target, mask the
spots, and word the edit prompt."""

import numpy as np
from PIL import Image

POINT_FRACTION = 0.2

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels


def point_box(size: tuple[int, int], fx: float, fy: float) -> Box:
    """A square a fifth of the short side, centred on the fractional point, kept inside."""
    w, h = size
    side = max(1, round(min(w, h) * POINT_FRACTION))
    x0 = min(max(round(fx * w - side / 2), 0), w - side)
    y0 = min(max(round(fy * h - side / 2), 0), h - side)
    return (x0, y0, x0 + side, y0 + side)


def region_box(size: tuple[int, int], box: list[float]) -> Box:
    """A fractional [x0, y0, x1, y1] box in pixels."""
    w, h = size
    x0, y0, x1, y1 = box
    return (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))


def has_alpha(img: Image.Image) -> bool:
    """True when the image has an alpha channel with any value below 255."""
    if "A" not in img.getbands():
        return False
    lo = img.getchannel("A").getextrema()[
        0
    ]  # one band: (min, max) of numbers, never per-band tuples
    return isinstance(lo, (int, float)) and lo < 255


def cut_out(img: Image.Image, mask: np.ndarray) -> Image.Image:
    """RGBA of `img` with everything outside `mask` transparent, cropped to the mask's bbox."""
    m = np.asarray(mask).astype(bool)
    rgba = img.convert("RGBA")
    if m.shape != (rgba.height, rgba.width):
        m = np.asarray(
            Image.fromarray(m.astype(np.uint8) * 255).resize(rgba.size, Image.Resampling.NEAREST)
        ).astype(bool)
    rows, cols = np.where(m)
    if rows.size == 0:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    a = np.asarray(rgba.getchannel("A")) * m
    rgba.putalpha(Image.fromarray(a.astype(np.uint8)))
    return rgba.crop((int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1))


def paste_into(target: Image.Image, subject: Image.Image, boxes: list[Box]) -> Image.Image:
    """`target` as RGB with `subject` fitted inside each box (aspect kept, centred), pasted
    through its alpha."""
    out = target.convert("RGB")
    subj = subject.convert("RGBA")
    for x0, y0, x1, y1 in boxes:
        bw, bh = x1 - x0, y1 - y0
        if bw < 1 or bh < 1:
            continue
        scale = min(bw / subj.width, bh / subj.height)
        w, h = max(1, round(subj.width * scale)), max(1, round(subj.height * scale))
        fitted = subj.resize((w, h), Image.Resampling.LANCZOS)
        out.paste(fitted, (x0 + (bw - w) // 2, y0 + (bh - h) // 2), fitted)
    return out


def spots_mask(size: tuple[int, int], spots: list[tuple[Box, np.ndarray | None]]) -> np.ndarray:
    """Bool H x W: the union of each spot's mask, or its box where it has none."""
    w, h = size
    out = np.zeros((h, w), dtype=bool)
    for (x0, y0, x1, y1), mask in spots:
        if mask is not None:
            out |= np.asarray(mask).astype(bool)
        else:
            out[max(y0, 0) : min(y1, h), max(x0, 0) : min(x1, w)] = True
    return out


def put_prompt(subject: str, spots: list[str], words: str | None) -> str:
    """The edit instruction for a picture with the subject already pasted into the spots."""
    where = ", ".join(spots)
    text = (
        f"The {subject} has been pasted roughly into these places: {where}. "
        f"Blend each pasted {subject} in so it looks like it was always there: match the "
        "perspective, lighting, colour cast, motion blur and scale of the picture around it, "
        "and add natural contact shadows and reflections. Keep each pasted item's own design "
        "and colours, and change nothing else in the picture."
    )
    if words and words.strip():
        text += f" {words.strip()}"
    return text
