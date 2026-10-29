import io

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import BoardItem
from app.errors import AppError
from app.ingest.common import IngestResult, ItemMeta, create_item, default_size
from app.ingest.sniff import sniff_image
from app.storage import files

MIN_EDGE = 256


def decode_image(data: bytes) -> Image.Image:
    """Validate magic bytes + decode (first frame for GIF). Raises AppError."""
    if sniff_image(data) is None:
        raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Not a supported image (jpeg/png/webp/gif)")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise AppError(400, "INVALID_IMAGE", "Image could not be decoded") from e
    if min(img.size) < MIN_EDGE:
        raise AppError(
            400, "IMAGE_TOO_SMALL", f"Shortest edge must be at least {MIN_EDGE}px", img.size
        )
    return img


def existing_by_sha(session: Session, board_id: str, sha: str) -> BoardItem | None:
    return session.scalars(
        select(BoardItem).where(
            BoardItem.board_id == board_id,
            BoardItem.sha256 == sha,
            BoardItem.removed_at.is_(None),
        )
    ).first()


def ingest_image(session: Session, board_id: str, data: bytes, meta: ItemMeta) -> IngestResult:
    if len(data) > get_settings().MAX_UPLOAD_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "Image exceeds the upload size limit")
    img = decode_image(data)
    mime, ext = sniff_image(data)  # type: ignore[misc]
    sha = files.sha256_hex(data)
    dup = existing_by_sha(session, board_id, sha)
    if dup is not None:
        if dup.staged and dup.explore_option_id:  # identical bytes to a hidden take: keep it
            from app.db.models import ExploreOption
            from app.explore.keep import keep_take

            opt = session.get(ExploreOption, dup.explore_option_id)
            if opt is not None and opt.status == "dismissed":
                dup.staged = False
                session.flush()
                return IngestResult(dup, deduped=True)

            at = (meta.x, meta.y) if meta.x is not None and meta.y is not None else None
            keep_take(session, dup.explore_option_id, dup.id, at)
        return IngestResult(dup, deduped=True)
    storage = files.save_original(data, sha, ext)
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    item = create_item(
        session, board_id, meta, kind="image", sha256=sha, storage_path=storage,
        thumb_path=thumb, mime=mime, width=img.size[0], height=img.size[1], w=w, h=h,
    )  # fmt: skip
    return IngestResult(item)
