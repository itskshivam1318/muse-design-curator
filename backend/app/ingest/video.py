import io
from dataclasses import dataclass
from typing import Any

import av
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.repos import items as items_repo
from app.errors import AppError
from app.imaging import dhash, hamming
from app.ingest.common import IngestResult, ItemMeta, create_item, default_size
from app.ingest.images import existing_by_sha
from app.ingest.sniff import sniff_video
from app.storage import files

SAMPLE_FPS = 2.0
MAX_FRAMES = 6
MIN_GAP_S = 1.0
SCENE_THRESHOLD = 10.0  # mean abs diff (0-255) on 32x32 greyscale
BLACK_LUMA = 12.0
DUP_HAMMING = 6


@dataclass
class Sampled:
    t: float
    image: Image.Image
    grey: np.ndarray
    score: float


def probe(data: bytes) -> tuple[float, int, int]:
    """(duration_s, width, height) via PyAV."""
    try:
        c: Any
        with av.open(io.BytesIO(data)) as c:
            vs: Any = next((s for s in c.streams if s.type == "video"), None)
            if vs is None:
                raise AppError(400, "INVALID_VIDEO", "No video stream found")
            dur = c.duration / av.time_base if c.duration else 0.0
            if not dur and vs.duration and vs.time_base:
                dur = float(vs.duration * vs.time_base)
            return dur, vs.codec_context.width, vs.codec_context.height
    except AppError:
        raise
    except Exception as e:
        raise AppError(400, "INVALID_VIDEO", "Video could not be decoded") from e


def sample_frames(data: bytes) -> list[Sampled]:
    out: list[Sampled] = []
    next_t = 0.0
    prev: np.ndarray | None = None
    c: Any
    with av.open(io.BytesIO(data)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        frame: Any
        for frame in c.decode(vs):
            t = float(frame.time) if frame.time is not None else next_t
            if t + 1e-6 < next_t:
                continue
            next_t = t + 1.0 / SAMPLE_FPS
            img = frame.to_image()
            grey = np.asarray(img.convert("L").resize((32, 32)), dtype=np.float32)
            score = 255.0 if prev is None else float(np.abs(grey - prev).mean())
            prev = grey
            out.append(Sampled(t, img, grey, score))
    return out


def select_keyframes(samples: list[Sampled]) -> list[Sampled]:
    """Top scene-change frames, >=1s apart, no near-black, no near-duplicates, max 6."""
    strong = sorted((s for s in samples if s.score >= SCENE_THRESHOLD), key=lambda s: -s.score)
    rest = sorted((s for s in samples if s.score < SCENE_THRESHOLD), key=lambda s: -s.score)
    picked: list[Sampled] = []
    hashes: list[int] = []
    for s in [*strong, *rest]:
        if len(picked) >= MAX_FRAMES:
            break
        if s.grey.mean() < BLACK_LUMA:
            continue
        if any(abs(s.t - p.t) < MIN_GAP_S for p in picked):
            continue
        h = dhash(s.image)
        if any(hamming(h, o) <= DUP_HAMMING for o in hashes):
            continue
        picked.append(s)
        hashes.append(h)
    return sorted(picked, key=lambda s: s.t)


def ingest_video(session: Session, board_id: str, data: bytes, meta: ItemMeta) -> IngestResult:
    st = get_settings()
    kind = sniff_video(data)
    if kind is None:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Not a supported video (mp4/mov/webm)")
    if len(data) > st.MAX_VIDEO_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "Video exceeds the size limit")
    mime, ext = kind
    duration, width, height = probe(data)
    if duration > st.MAX_VIDEO_SECONDS:
        raise AppError(400, "VIDEO_TOO_LONG", f"Video exceeds {st.MAX_VIDEO_SECONDS}s")
    sha = files.sha256_hex(data)
    dup = existing_by_sha(session, board_id, sha)
    if dup is not None:
        return IngestResult(dup, deduped=True)
    try:
        keyframes = select_keyframes(sample_frames(data))
    except Exception as e:
        raise AppError(400, "INVALID_VIDEO", "Video could not be decoded") from e
    storage = files.save_original(data, sha, ext)
    w, h = default_size(width, height)
    item = create_item(
        session, board_id, meta, kind="video", sha256=sha, storage_path=storage, mime=mime,
        width=width, height=height, w=w, h=h,
    )  # fmt: skip
    attach_frames(session, item.id, [(s.image, int(s.t * 1000)) for s in keyframes])
    if not keyframes:
        items_repo.update(
            session, item.id, parse_status="failed", parse_error_code="NO_USABLE_FRAMES"
        )
    else:
        chosen = items_repo.frames(session, item.id)
        mid = chosen[len(chosen) // 2]
        _choose(session, item.id, mid.id)
    return IngestResult(item)


def attach_frames(session: Session, item_id: str, frames: list[tuple[Image.Image, int]]) -> None:
    for img, t_ms in frames:
        sha, rel = files.save_frame(img)
        items_repo.add_frame(session, item_id=item_id, t_ms=t_ms, sha256=sha, storage_path=rel)


def _choose(session: Session, item_id: str, frame_id: str) -> None:
    """Mark exactly one frame chosen and point the item thumbnail at it."""
    chosen = None
    for f in items_repo.frames(session, item_id):
        f.chosen = f.id == frame_id
        if f.chosen:
            chosen = f
    if chosen is None:
        raise AppError(400, "INVALID_FRAME", "Frame does not belong to this item")
    with Image.open(files.abs_path(chosen.storage_path)) as im:
        thumb = files.save_thumb(im, chosen.sha256)
    items_repo.update(session, item_id, thumb_path=thumb)


choose_frame = _choose
