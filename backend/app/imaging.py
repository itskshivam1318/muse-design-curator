"""Small pure image helpers."""

from typing import Any

from PIL import Image


def dhash(img: Image.Image, size: int = 8) -> int:
    """Difference hash: size*size bits comparing horizontally adjacent greyscale pixels."""
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px: list[Any] = list(g.get_flattened_data())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
