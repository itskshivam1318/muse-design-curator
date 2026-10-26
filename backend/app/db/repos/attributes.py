from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AttributeEvent, ItemAttribute


def upsert(session: Session, item_id: str, key: str, **fields: Any) -> ItemAttribute:
    """Insert or merge the current record for (item_id, key). History lives in events."""
    row = session.scalar(
        select(ItemAttribute).where(ItemAttribute.item_id == item_id, ItemAttribute.key == key)
    )
    if row is None:
        row = ItemAttribute(item_id=item_id, key=key, **fields)
        session.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    session.flush()
    return row


def for_item(session: Session, item_id: str) -> list[ItemAttribute]:
    q = select(ItemAttribute).where(ItemAttribute.item_id == item_id).order_by(ItemAttribute.key)
    return list(session.scalars(q))


def append_event(session: Session, **fields: Any) -> AttributeEvent:
    event = AttributeEvent(**fields)
    session.add(event)
    session.flush()
    return event


def events(session: Session, item_id: str, key: str | None = None) -> list[AttributeEvent]:
    q = select(AttributeEvent).where(AttributeEvent.item_id == item_id)
    if key is not None:
        q = q.where(AttributeEvent.key == key)
    return list(session.scalars(q.order_by(AttributeEvent.id)))
