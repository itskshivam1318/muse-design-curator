from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.ids import now_iso
from app.db.models import BoardItem, ItemFrame


def create(session: Session, **fields: Any) -> BoardItem:
    item = BoardItem(**fields)
    session.add(item)
    session.flush()
    return item


def get(session: Session, item_id: str) -> BoardItem | None:
    return session.get(BoardItem, item_id)


def list_active(session: Session, board_id: str) -> list[BoardItem]:
    q = select(BoardItem).where(BoardItem.board_id == board_id, BoardItem.removed_at.is_(None))
    return list(session.scalars(q.order_by(BoardItem.z, BoardItem.id)))


def children(session: Session, parent_item_id: str) -> list[BoardItem]:
    q = select(BoardItem).where(BoardItem.parent_item_id == parent_item_id)
    return list(session.scalars(q.order_by(BoardItem.id)))


def update_position(
    session: Session, item_id: str, x: float, y: float, w: float, h: float, z: int
) -> BoardItem | None:
    item = session.get(BoardItem, item_id)
    if item is None:
        return None
    item.x, item.y, item.w, item.h, item.z = x, y, w, h, z
    session.flush()
    return item


def update(session: Session, item_id: str, **fields: Any) -> BoardItem | None:
    item = session.get(BoardItem, item_id)
    if item is None:
        return None
    for k, v in fields.items():
        setattr(item, k, v)
    session.flush()
    return item


def soft_delete(session: Session, item_id: str) -> BoardItem | None:
    return update(session, item_id, removed_at=now_iso())


def add_frame(session: Session, **fields: Any) -> ItemFrame:
    frame = ItemFrame(**fields)
    session.add(frame)
    session.flush()
    return frame


def frames(session: Session, item_id: str) -> list[ItemFrame]:
    q = select(ItemFrame).where(ItemFrame.item_id == item_id).order_by(ItemFrame.t_ms)
    return list(session.scalars(q))
