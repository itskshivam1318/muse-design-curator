import base64
import binascii

from sqlalchemy.orm import Session

from app.db.repos import items as items_repo
from app.errors import AppError
from app.ingest.common import IngestResult, ItemMeta, create_item, default_size
from app.ingest.images import decode_image, existing_by_sha, ingest_image
from app.ingest.video import MAX_FRAMES, attach_frames, choose_frame
from app.storage import files


def b64decode(s: str) -> bytes:
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as e:
        raise AppError(400, "INVALID_BASE64", "Capture payload is not valid base64") from e


def ingest_capture_image(
    session: Session, board_id: str, image_b64: str, meta: ItemMeta
) -> IngestResult:
    return ingest_image(session, board_id, b64decode(image_b64), meta)


def ingest_capture_frames(
    session: Session, board_id: str, frames_b64: list[str], meta: ItemMeta
) -> IngestResult:
    """A video captured as stills by the extension: a video item with frames, no video file."""
    if not 1 <= len(frames_b64) <= MAX_FRAMES:
        raise AppError(400, "VALIDATION_ERROR", f"frames_b64 must hold 1-{MAX_FRAMES} frames")
    raw = [b64decode(f) for f in frames_b64]
    images = [decode_image(r) for r in raw]
    sha = files.sha256_hex(b"".join(files.sha256_hex(r).encode() for r in raw))
    dup = existing_by_sha(session, board_id, sha)
    if dup is not None:
        return IngestResult(dup, deduped=True)
    width, height = images[0].size
    w, h = default_size(width, height)
    item = create_item(
        session, board_id, meta, kind="video", sha256=sha, width=width, height=height, w=w, h=h
    )
    attach_frames(session, item.id, [(im, i * 1000) for i, im in enumerate(images)])
    stored = items_repo.frames(session, item.id)
    choose_frame(session, item.id, stored[len(stored) // 2].id)
    return IngestResult(item)
