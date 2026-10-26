import io

import numpy as np
from PIL import Image

from app.measure.crops import crop_part
from app.measure.palette import (
    delta_e,
    dominant_lab,
    mask_ratio,
    masked_palette,
    nearest_color_name,
    palette_count,
    to_rgb_array,
)
from app.measure.shape import (
    SHAPE_DIFFERENT_MAX,
    SHAPE_SAME_MIN,
    shape_descriptor,
    shape_similarity,
)

N = 200


def _circle(r=60, n=N):
    yy, xx = np.mgrid[:n, :n]
    return (yy - n / 2) ** 2 + (xx - n / 2) ** 2 <= r**2


def _square(half=50, n=N):
    m = np.zeros((n, n), bool)
    m[n // 2 - half : n // 2 + half, n // 2 - half : n // 2 + half] = True
    return m


def _cushion(n=N):
    # superellipse |x|^4+|y|^4 <= r^4 : a rounded square
    yy, xx = np.mgrid[:n, :n]
    x, y = (xx - n / 2) / 60, (yy - n / 2) / 60
    return x**4 + y**4 <= 1


def _flat(colors):
    img = np.zeros((90, 90, 3), np.uint8)
    for i, c in enumerate(colors):
        img[:, i * 30 : (i + 1) * 30] = c
    return img


def test_circle_vs_circle():
    assert shape_similarity(shape_descriptor(_circle(60)), shape_descriptor(_circle(30))) >= 0.95


def test_circle_vs_square_low():
    assert shape_similarity(shape_descriptor(_circle()), shape_descriptor(_square())) <= 0.6


def test_cushion_between():
    c = shape_descriptor(_cushion())
    s_round = shape_similarity(c, shape_descriptor(_circle()))
    s_sq = shape_similarity(c, shape_descriptor(_square(55)))
    assert SHAPE_DIFFERENT_MAX < s_round < 1.0
    assert SHAPE_DIFFERENT_MAX < s_sq < 1.0


def test_scale_and_rotation_invariant():
    rect = np.zeros((N, N), bool)
    rect[70:130, 40:160] = True
    a = shape_descriptor(rect)
    small = np.zeros((N, N), bool)
    small[85:115, 70:130] = True
    assert shape_similarity(a, shape_descriptor(small)) >= 0.95
    assert shape_similarity(a, shape_descriptor(np.rot90(rect))) >= 0.95


def test_descriptor_shape():
    d = shape_descriptor(_circle())
    assert len(d["hu"]) == 7
    assert len(d["contour"]) == 64


def test_thresholds():
    assert SHAPE_SAME_MIN == 0.85 and SHAPE_DIFFERENT_MAX == 0.60


def test_palette_count_three_colours():
    img = _flat([(220, 30, 30), (30, 160, 40), (30, 40, 220)])
    assert palette_count(img, None) == 3
    assert palette_count(img, np.ones((90, 90), bool)) == 3


def test_palette_count_merges_close_and_drops_small():
    img = _flat([(200, 30, 30), (202, 32, 30), (30, 40, 220)])
    assert palette_count(img, None) == 2
    img = np.zeros((100, 100, 3), np.uint8)
    img[:] = (240, 240, 240)
    img[:2, :2] = (255, 0, 0)  # 0.04% share
    assert palette_count(img, None) == 1


def test_masked_palette_basic():
    img = _flat([(255, 0, 0), (0, 0, 255), (0, 255, 0)])
    mask = np.zeros((90, 90), bool)
    mask[:, :60] = True
    pal = masked_palette(img, mask, k=5)
    assert len(pal) == 2
    assert abs(sum(p["share"] for p in pal) - 1) < 1e-6
    assert {p["hex"] for p in pal} == {"#FF0000", "#0000FF"}
    assert pal[0]["share"] >= pal[1]["share"]
    assert masked_palette(img, mask, k=5) == pal  # deterministic
    assert dominant_lab(pal) == pal[0]["lab"]


def test_delta_e_and_names():
    red = masked_palette(_flat([(255, 0, 0)] * 3), None)[0]["lab"]
    assert delta_e(red, red) == 0
    assert delta_e(red, (50.0, 0.0, 0.0)) > 20
    assert nearest_color_name(red) == "red"
    white = masked_palette(_flat([(255, 255, 255)] * 3), None)[0]["lab"]
    assert nearest_color_name(white) == "white"
    assert nearest_color_name(masked_palette(_flat([(0, 0, 0)] * 3), None)[0]["lab"]) == "black"


def test_mask_ratio():
    a, b = _circle(30), _circle(60)
    assert abs(mask_ratio(a, b) - 0.25) < 0.02
    assert mask_ratio(a, np.zeros_like(a)) == 0.0


def test_crop_part_png_grey_outside():
    img = np.full((100, 100, 3), (255, 0, 0), np.uint8)
    mask = np.zeros((100, 100), bool)
    mask[40:60, 40:60] = True
    out = crop_part(img, mask, pad=0.05)
    im = Image.open(io.BytesIO(out))
    assert im.format == "PNG"
    arr = np.array(im.convert("RGB"))
    assert arr.shape[0] < 100
    assert tuple(arr[0, 0]) == (128, 128, 128)
    assert tuple(arr[arr.shape[0] // 2, arr.shape[1] // 2]) == (255, 0, 0)


def test_to_rgb_array():
    buf = io.BytesIO()
    Image.new("RGBA", (8, 6), (1, 2, 3, 255)).save(buf, "PNG")
    a = to_rgb_array(buf.getvalue())
    assert a.shape == (6, 8, 3) and a.dtype == np.uint8
