import numpy as np
import pytest
from PIL import Image

from app.plugins.registry import load_builtin_module

cutout = load_builtin_module("cleanup", "cutout").cutout


def picture() -> tuple[Image.Image, np.ndarray]:
    im = Image.fromarray(np.full((100, 200, 3), 40, np.uint8))
    mask = np.zeros((100, 200), bool)
    mask[20:60, 50:150] = True
    return im, mask


def test_cutout_transparent_outside_mask() -> None:
    im, mask = picture()
    out = cutout(im, mask, None, "transparent", 0.04)
    assert out.mode == "RGBA"
    assert out.size == (100 + 2 * 4, 40 + 2 * 2)  # bbox 100x40 plus 4% each side
    a = np.asarray(out)[..., 3]
    assert a[0, 0] == 0 and a[a.shape[0] // 2, a.shape[1] // 2] == 255
    assert int((a == 255).sum()) == int(mask.sum())


def test_margin_clamps_to_the_image() -> None:
    im = Image.fromarray(np.zeros((50, 50, 3), np.uint8))
    mask = np.ones((50, 50), bool)
    assert cutout(im, mask, None, "transparent", 0.5).size == (50, 50)


def test_cutout_white_background() -> None:
    im, mask = picture()
    out = cutout(im, mask, None, "white")
    assert out.mode == "RGB" and out.size == (100, 40)
    arr = np.asarray(out)
    assert tuple(arr[0, 0]) == (255, 255, 255) or mask[20, 50]
    outside = ~mask[20:60, 50:150]
    assert not outside.any() or (arr[outside] == 255).all()
    assert tuple(arr[20, 50]) == (40, 40, 40)


def test_white_background_outside_pixels() -> None:
    im = Image.fromarray(np.full((10, 10, 3), 40, np.uint8))
    mask = np.zeros((10, 10), bool)
    mask[2:8, 2:8] = True
    mask[2, 2] = False
    arr = np.asarray(cutout(im, mask, None, "white"))
    assert tuple(arr[0, 0]) == (255, 255, 255) and tuple(arr[3, 3]) == (40, 40, 40)


def test_cutout_empty_mask_raises_valueerror() -> None:
    im, _ = picture()
    with pytest.raises(ValueError):
        cutout(im, np.zeros((100, 200), bool), None)
    with pytest.raises(ValueError):
        cutout(im, np.zeros((100, 200), bool), (0, 0, 50, 50))
