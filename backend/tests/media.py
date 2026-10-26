"""Generated media for tests; nothing is downloaded."""

import io
from fractions import Fraction

import av
import numpy as np
from PIL import Image


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (400, 300), seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, fmt)
    return buf.getvalue()


def _pattern(kind: int, w: int, h: int) -> np.ndarray:
    """Distinct block mosaics (solid colours/monotone gradients collapse to one dHash)."""
    rng = np.random.default_rng(1000 + kind)
    cells = rng.integers(40, 255, (9, 9, 3), dtype=np.uint8)
    return np.kron(cells, np.ones((h // 9 + 1, w // 9 + 1, 1), dtype=np.uint8))[:h, :w]


def video_bytes(segments: list[int | None], seg_seconds: float = 2.0, fps: int = 10) -> bytes:
    """MP4 with one segment per entry: pattern index, or None for black."""
    w, h = 320, 240
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as c:
        stream = c.add_stream("mpeg4", rate=fps)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        stream.time_base = Fraction(1, fps)
        n = 0
        for seg in segments:
            arr = np.zeros((h, w, 3), np.uint8) if seg is None else _pattern(seg, w, h)
            for _ in range(int(seg_seconds * fps)):
                frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
                frame.pts = n
                n += 1
                for pkt in stream.encode(frame):
                    c.mux(pkt)
        for pkt in stream.encode():
            c.mux(pkt)
    return buf.getvalue()
