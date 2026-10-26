"""Generate the committed fixture corpus: synthetic images + manifest.jsonl, no network.

    cd backend && uv run python tests/fixtures/corpus/make_fixtures.py

Images are flat shapes on lightly textured backgrounds (watch-like circles, garment-like
silhouettes, room-like blocks, UI-like panels). Everything is labelled source "test_fixture",
CC0-1.0, and is deterministic, so re-running rewrites identical files.
"""

from __future__ import annotations

import colorsys
import io
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
IMAGES = HERE / "images"
SIZE = 256
PER_DOMAIN = 8
CREATOR = "Design Language Engine test fixtures"
FETCHED_AT = "2026-10-26T00:00:00.000+00:00"
LANDING_PREFIX = "backend/tests/fixtures/corpus/images/"
Colour = tuple[int, int, int]


def hsv(h: float, s: float, v: float) -> Colour:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def texture(rng: np.random.Generator, base: Colour) -> Image.Image:
    """Flat colour plus smooth low-amplitude noise so no two images share a dHash."""
    low = rng.normal(0, 14, (6, 6, 1))
    big = (
        np.asarray(
            Image.fromarray(((low + 128).clip(0, 255)).astype(np.uint8)[:, :, 0]).resize(
                (SIZE, SIZE), Image.Resampling.BICUBIC
            )
        ).astype(float)[:, :, None]
        - 128
    )
    arr = (np.array(base, dtype=float)[None, None, :] + big).clip(0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def watch(i: int, rng: np.random.Generator) -> Image.Image:
    hue = 0.04 + 0.11 * i
    img = texture(rng, hsv(hue + 0.5, 0.2, 0.85))
    d = ImageDraw.Draw(img)
    cx, cy, r = 128 + rng.integers(-14, 14), 128 + rng.integers(-10, 10), 70 + rng.integers(0, 18)
    d.rectangle([cx - 24, 0, cx + 24, SIZE], fill=hsv(hue, 0.5, 0.3 + 0.05 * i))  # strap
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=hsv(hue, 0.15, 0.2))  # case
    d.ellipse([cx - r + 9, cy - r + 9, cx + r - 9, cy + r - 9], fill=hsv(hue + 0.1, 0.6, 0.8))
    for k in range(12):
        a = k * np.pi / 6
        d.line([cx + (r - 18) * np.sin(a), cy - (r - 18) * np.cos(a),
                cx + (r - 28) * np.sin(a), cy - (r - 28) * np.cos(a)], fill=(250, 250, 245), width=3)  # fmt: skip
    ha = rng.uniform(0, 6.28)
    d.line([cx, cy, cx + 32 * np.sin(ha), cy - 32 * np.cos(ha)], fill=(250, 250, 245), width=5)
    d.line([cx, cy, cx + 48 * np.sin(ha + 2), cy - 48 * np.cos(ha + 2)], fill=(250, 250, 245), width=3)  # fmt: skip
    return img


def fashion(i: int, rng: np.random.Generator) -> Image.Image:
    hue = 0.55 + 0.09 * i
    img = texture(rng, hsv(hue + 0.4, 0.08, 0.92))
    d = ImageDraw.Draw(img)
    sh = 40 + int(rng.integers(0, 24))
    hem = 215 + int(rng.integers(-10, 25))
    flare = 20 + int(rng.integers(0, 40))
    body = hsv(hue, 0.45, 0.35 + 0.07 * (i % 5))
    d.polygon([(100, 40), (156, 40), (128 + sh, 70), (150 + flare, hem), (106 - flare, hem),
               (128 - sh, 70)], fill=body)  # fmt: skip
    d.ellipse([112, 28, 144, 56], fill=hsv(hue, 0.2, 0.9))
    d.line([128, 56, 128, hem], fill=hsv(hue, 0.5, 0.2), width=2)
    return img


def interior(i: int, rng: np.random.Generator) -> Image.Image:
    hue = 0.08 + 0.12 * i
    img = texture(rng, hsv(hue, 0.18, 0.88))
    d = ImageDraw.Draw(img)
    floor = 150 + int(rng.integers(-12, 24))
    d.rectangle([0, floor, SIZE, SIZE], fill=hsv(hue + 0.05, 0.4, 0.45))
    wx = int(rng.integers(20, 120))
    d.rectangle([wx, 28, wx + 70 + 10 * (i % 3), 110], fill=hsv(0.58, 0.25, 0.95))  # window
    sx, sw = int(rng.integers(10, 90)), int(rng.integers(90, 150))
    d.rectangle([sx, floor - 36, sx + sw, floor + 18], fill=hsv(hue + 0.3, 0.45, 0.5))  # sofa
    d.rectangle([sx + sw + 18, floor - 70, sx + sw + 26, floor + 6], fill=(40, 40, 40))  # lamp
    return img


def ui(i: int, rng: np.random.Generator) -> Image.Image:
    hue = 0.6 + 0.07 * i
    img = texture(rng, hsv(hue, 0.04, 0.97))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, SIZE, 30], fill=hsv(hue, 0.6, 0.35 + 0.05 * (i % 4)))  # header
    side = 50 + int(rng.integers(0, 30))
    d.rectangle([0, 30, side, SIZE], fill=hsv(hue, 0.15, 0.88))  # sidebar
    for k in range(int(rng.integers(2, 4))):
        top = 48 + k * 62
        d.rectangle([side + 14, top, SIZE - 14, top + 48], fill=(255, 255, 255), outline=hsv(hue, 0.1, 0.7))  # fmt: skip
        d.rectangle([side + 22, top + 12, side + 22 + int(rng.integers(40, 100)), top + 20], fill=hsv(hue, 0.3, 0.4))  # fmt: skip
    d.rounded_rectangle([SIZE - 80, SIZE - 38, SIZE - 20, SIZE - 14], 6, fill=hsv(0.08, 0.8, 0.95))
    return img


DOMAINS = {"watch": watch, "fashion": fashion, "interior": interior, "ui": ui}


def jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def entry(source_id: str, domain: str, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": f"cx_test_fixture_{source_id}",
        "domain": domain,
        "source": "test_fixture",
        "source_id": source_id,
        "landing_url": f"{LANDING_PREFIX}{source_id}.jpg",
        "image_url": f"images/{source_id}.jpg",
        "creator_name": CREATOR,
        "license_code": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution_text": f"{source_id}, {CREATOR}, CC0 1.0 (synthetic test image)",
        "fetched_at": FETCHED_AT,
    }
    row.update(over)
    return row


def main() -> None:
    if IMAGES.exists():
        shutil.rmtree(IMAGES)
    IMAGES.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    originals: dict[str, bytes] = {}
    for d_index, (domain, draw) in enumerate(DOMAINS.items()):
        for i in range(PER_DOMAIN):
            sid = f"{domain}_{i + 1:02d}"
            rng = np.random.default_rng(1000 * (d_index + 1) + i)
            data = jpeg(draw(i, rng))
            (IMAGES / f"{sid}.jpg").write_bytes(data)
            originals[sid] = data
            rows.append(entry(sid, domain))

    # deliberate edge cases (all in the first domain)
    first = "watch"
    (IMAGES / "watch_dup.jpg").write_bytes(originals["watch_01"])  # byte-identical duplicate
    rows.append(entry("watch_dup", first))
    with Image.open(IMAGES / "watch_02.jpg") as im:  # resized near-duplicate
        small = im.resize((192, 192), Image.Resampling.LANCZOS)
    (IMAGES / "watch_02_small.jpg").write_bytes(jpeg(small))
    rows.append(entry("watch_02_small", first))
    rng = np.random.default_rng(99)
    (IMAGES / "watch_reserved.jpg").write_bytes(jpeg(watch(11, rng)))
    rows.append(
        entry("watch_reserved", first, license_code="All rights reserved", license_url=None)
    )
    (IMAGES / "watch_by_nocreator.jpg").write_bytes(jpeg(watch(12, np.random.default_rng(98))))
    rows.append(
        entry(
            "watch_by_nocreator",
            first,
            license_code="CC-BY-4.0",
            creator_name=None,
            license_url="https://creativecommons.org/licenses/by/4.0/",
        )
    )
    rows.append(entry("watch_missing", first))  # manifest entry whose image file does not exist

    with (HERE / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(rows)} manifest entries, {len(list(IMAGES.iterdir()))} images")


if __name__ == "__main__":
    main()
