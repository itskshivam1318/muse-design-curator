from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import BoardItem
from app.db.repos import items as items_repo

GAP = 24
MAX_SIDE = 320


@dataclass
class ItemMeta:
    origin: str = "upload"
    filename: str | None = None
    source_url: str | None = None
    page_url: str | None = None
    page_title: str | None = None
    creator_handle: str | None = None
    x: float | None = None
    y: float | None = None


@dataclass
class IngestResult:
    item: BoardItem
    deduped: bool = False


def default_size(width: int, height: int) -> tuple[float, float]:
    scale = MAX_SIDE / max(width, height, 1)
    return round(width * scale, 2), round(height * scale, 2)


def place(session: Session, board_id: str, meta: ItemMeta) -> tuple[float, float, int]:
    """Drop point if given, else right of the right-most item. Returns (x, y, z)."""
    active = items_repo.list_active(session, board_id)
    z = max((i.z for i in active), default=-1) + 1
    if meta.x is not None and meta.y is not None:
        return meta.x, meta.y, z
    if not active:
        return 0.0, 0.0, z
    right = max(active, key=lambda i: i.x + i.w)
    return right.x + right.w + GAP, right.y, z


def create_item(session: Session, board_id: str, meta: ItemMeta, **fields: Any) -> BoardItem:
    x, y, z = place(session, board_id, meta)
    return items_repo.create(
        session,
        board_id=board_id,
        origin=meta.origin,
        original_filename=meta.filename,
        source_url=meta.source_url,
        page_url=meta.page_url,
        page_title=meta.page_title,
        creator_handle=meta.creator_handle,
        x=x,
        y=y,
        z=z,
        **fields,
    )
