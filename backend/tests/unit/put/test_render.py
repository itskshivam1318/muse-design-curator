import numpy as np
from PIL import Image

from app.put.render import (
    cut_out,
    paste_into,
    point_box,
    put_prompt,
    region_box,
    spots_mask,
)


def test_point_box_is_a_fifth_of_the_short_side_centred():
    assert point_box((1000, 500), 0.5, 0.5) == (450, 200, 550, 300)


def test_point_box_clamps_inside_the_image():
    assert point_box((1000, 500), 0.0, 1.0) == (0, 400, 100, 500)


def test_region_box_converts_fractions():
    assert region_box((200, 100), [0.1, 0.2, 0.6, 0.9]) == (20, 20, 120, 90)


def test_paste_fits_and_centres():
    target = Image.new("RGB", (100, 100), "white")
    subject = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    out = paste_into(target, subject, [(0, 0, 40, 20)])
    assert out.mode == "RGB"
    assert out.getpixel((20, 10)) == (255, 0, 0)
    assert out.getpixel((5, 10)) == (255, 255, 255)
    assert out.getpixel((35, 10)) == (255, 255, 255)


def test_paste_respects_alpha():
    target = Image.new("RGB", (20, 20), (0, 0, 255))
    subject = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    for x in range(5):
        for y in range(10):
            subject.putpixel((x, y), (255, 0, 0, 0))
    out = paste_into(target, subject, [(0, 0, 10, 10)])
    assert out.getpixel((2, 5)) == (0, 0, 255)
    assert out.getpixel((7, 5)) == (255, 0, 0)


def test_spots_mask_unions_mask_and_box():
    m = np.zeros((20, 20), dtype=bool)
    m[2:5, 2:5] = True
    out = spots_mask((20, 20), [((0, 0, 10, 10), m), ((10, 10, 15, 14), None)])
    expected = m.copy()
    expected[10:14, 10:15] = True
    assert out.dtype == bool
    assert (out == expected).all()


def test_cut_out_crops_to_mask():
    img = Image.new("RGB", (10, 10), (9, 9, 9))
    m = np.zeros((10, 10), dtype=bool)
    m[2:6, 3:5] = True
    m[3, 3] = False
    out = cut_out(img, m)
    assert out.mode == "RGBA"
    assert out.size == (2, 4)
    assert out.getpixel((0, 1))[3] == 0
    assert out.getpixel((1, 1))[3] == 255


def test_prompt_carries_words_and_only_these():
    p = put_prompt("bronze wheel", ["Front wheel", "Rear wheel"], "keep the blur")
    for s in ("bronze wheel", "Front wheel", "Rear wheel", "keep the blur", "change nothing else"):
        assert s in p
    q = put_prompt("bronze wheel", ["Front wheel"], None)
    assert not q.rstrip().endswith((",", ";", ":", "-"))
