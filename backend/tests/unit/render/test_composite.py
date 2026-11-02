"""composite_in_region: the edit lands only inside the region; outside stays byte-identical."""

import io

import numpy as np
from PIL import Image

from app.analysis.types import Region
from app.render.composite import composite_in_region

W, H = 200, 160
BOX = Region(kind="box", box=[0.4, 0.4, 0.6, 0.6])


def png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def arr(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB")).astype(int)


def source() -> bytes:
    rng = np.random.default_rng(1)
    return png(rng.integers(0, 256, (H, W, 3), dtype=np.uint8))


def edited(size: tuple[int, int] = (W, H)) -> bytes:
    return png(np.full((size[1], size[0], 3), (255, 0, 0), dtype=np.uint8))


def far_from(x0: int, y0: int, x1: int, y1: int, margin: int) -> np.ndarray:
    """True where a pixel is more than `margin` px away from the rectangle."""
    ys, xs = np.mgrid[0:H, 0:W]
    return (xs < x0 - margin) | (xs >= x1 + margin) | (ys < y0 - margin) | (ys >= y1 + margin)


def test_composite_outside_box_identical() -> None:
    src = source()
    out = composite_in_region(src, edited(), BOX, None)
    outside = far_from(80, 64, 120, 96, 0)
    assert np.array_equal(arr(out)[outside], arr(src)[outside])


def test_composite_inside_takes_edit() -> None:
    src = source()
    out = composite_in_region(src, edited(), BOX, None)
    inside = (slice(70, 90), slice(90, 110))  # the box centre
    assert np.abs(arr(out)[inside] - arr(src)[inside]).mean() > 0
    assert np.abs(arr(out)[78:82, 98:102] - (255, 0, 0)).max() < 16  # nearly all edit


def test_composite_resizes_the_edit_to_the_source() -> None:
    src = source()
    out = composite_in_region(src, edited((64, 64)), BOX, None)
    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (W, H)


def test_composite_with_mask_follows_the_mask() -> None:
    src = source()
    mask = np.zeros((H // 2, W // 2), dtype=bool)  # a smaller mask is scaled to the source
    mask[10:30, 10:30] = True  # source px 20..60
    region = Region(kind="mask", box=[0.0, 0.0, 1.0, 1.0], mask_url="/api/media/masks/x.png")
    out = composite_in_region(src, edited(), region, mask)
    outside = far_from(20, 20, 60, 60, 0)
    assert np.array_equal(arr(out)[outside], arr(src)[outside])
    assert np.abs(arr(out)[38:42, 38:42] - (255, 0, 0)).max() < 16


def test_zero_feather_is_a_hard_edge() -> None:
    src = source()
    out = composite_in_region(src, edited(), BOX, None, feather_px=0)
    outside = far_from(80, 64, 120, 96, 0)
    assert np.array_equal(arr(out)[outside], arr(src)[outside])
    assert (arr(out)[64:96, 80:120] == (255, 0, 0)).all()
