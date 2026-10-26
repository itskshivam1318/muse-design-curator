"""Prepare an isolated, offline data directory for the Playwright end-to-end suite.

    REASONING_PROVIDER=mock SEGMENTATION_PROVIDER=mock EMBEDDER=mock \
    DATA_DIR=./data/e2e DATABASE_URL=sqlite:///./data/e2e/dle.sqlite \
    uv run python scripts/e2e_prepare.py

Wipes DATA_DIR (it must be an `e2e` directory), seeds the four demo boards from the committed
fixture corpus, and writes the files the specs need under DATA_DIR/site (served by a static
server during the run): five upload images, a page with an og:image, a page with a plain <img>
for the extension, and a 3-second MP4 generated with PyAV. Nothing is downloaded and no model
API is called: the script refuses to run unless every provider is the mock.
"""

from __future__ import annotations

import io
import shutil
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import av
import numpy as np
from PIL import Image, ImageOps

from app.config import REPO_ROOT, data_dir, get_settings

FIXTURE_IMAGES = REPO_ROOT / "backend" / "tests" / "fixtures" / "corpus" / "images"
UPLOADS = ["watch_01.jpg", "watch_02.jpg", "watch_03.jpg", "watch_04.jpg", "watch_05.jpg"]
OG_IMAGE = "watch_06.jpg"
CAPTURE_IMAGE = "watch_07.jpg"
VIDEO_FRAMES = ["watch_08.jpg", "watch_06.jpg", "watch_07.jpg"]  # one second each
VIDEO_SIZE = (480, 360)


def _guard() -> Path:
    st = get_settings()
    live = {
        "REASONING_PROVIDER": st.REASONING_PROVIDER,
        "SEGMENTATION_PROVIDER": st.SEGMENTATION_PROVIDER,
        "EMBEDDER": st.EMBEDDER,
    }
    not_mock = {k: v for k, v in live.items() if v != "mock"}
    if not_mock:
        raise SystemExit(f"e2e_prepare: refusing to run with live providers: {not_mock}")
    root = data_dir(st)
    if "e2e" not in root.name:
        raise SystemExit(f"e2e_prepare: DATA_DIR must be an e2e directory, got {root}")
    if "e2e" not in st.DATABASE_URL:
        raise SystemExit("e2e_prepare: DATABASE_URL must point inside the e2e directory")
    return root


def mp4_bytes(paths: list[Path], seconds_each: float = 1.0, fps: int = 10) -> bytes:
    """An MP4 that shows each image for `seconds_each` (distinct scenes -> distinct key frames)."""
    w, h = VIDEO_SIZE
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as c:
        stream = c.add_stream("mpeg4", rate=fps)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        stream.time_base = Fraction(1, fps)
        n = 0
        for p in paths:
            with Image.open(p) as im:
                arr = np.asarray(ImageOps.fit(im.convert("RGB"), (w, h)))
            for _ in range(int(seconds_each * fps)):
                frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
                frame.pts = n
                n += 1
                for pkt in stream.encode(frame):
                    c.mux(pkt)
        for pkt in stream.encode():
            c.mux(pkt)
    return buf.getvalue()


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<meta property="og:title" content="{title}">
{og}
</head><body><h1>{title}</h1>{body}</body></html>
"""


def write_site(site: Path) -> None:
    site.mkdir(parents=True, exist_ok=True)
    for name in UPLOADS:
        shutil.copyfile(FIXTURE_IMAGES / name, site / name)
    shutil.copyfile(FIXTURE_IMAGES / OG_IMAGE, site / "og.jpg")
    shutil.copyfile(FIXTURE_IMAGES / CAPTURE_IMAGE, site / "capture.jpg")
    (site / "article.html").write_text(
        PAGE.format(
            title="Fixture article", og='<meta property="og:image" content="/og.jpg">',
            body="<p>A page whose preview image is a watch.</p>",
        )
    )  # fmt: skip
    (site / "gallery.html").write_text(
        PAGE.format(
            title="Fixture gallery", og="",
            body='<img id="watch" src="/capture.jpg" alt="A watch" width="400">',
        )
    )  # fmt: skip
    (site / "clip.mp4").write_bytes(mp4_bytes([FIXTURE_IMAGES / n for n in VIDEO_FRAMES]))


def main() -> int:
    root = _guard()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    write_site(root / "site")

    import seed  # scripts/seed.py, alongside this file

    from app.api import deps

    session = deps.new_session()
    try:
        seed.index_all(session, fixtures=True)
        boards = seed.seed(session)
        session.commit()
    finally:
        session.close()
    print(f"e2e: seeded {len(boards)} boards, site files in {root / 'site'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
