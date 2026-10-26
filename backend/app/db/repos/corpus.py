from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CorpusAttribute, CorpusItem


def create(session: Session, **fields: Any) -> CorpusItem:
    row = CorpusItem(**fields)
    session.add(row)
    session.flush()
    return row


def get(session: Session, corpus_item_id: str) -> CorpusItem | None:
    return session.get(CorpusItem, corpus_item_id)


def update(session: Session, corpus_item_id: str, **fields: Any) -> CorpusItem | None:
    row = session.get(CorpusItem, corpus_item_id)
    if row is None:
        return None
    for k, v in fields.items():
        setattr(row, k, v)
    session.flush()
    return row


def set_attribute(session: Session, item_id: str, key: str, **fields: Any) -> CorpusAttribute:
    row = session.get(CorpusAttribute, (item_id, key))
    if row is None:
        row = CorpusAttribute(item_id=item_id, key=key, **fields)
        session.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    session.flush()
    return row


def attributes(session: Session, item_id: str) -> list[CorpusAttribute]:
    q = select(CorpusAttribute).where(CorpusAttribute.item_id == item_id)
    return list(session.scalars(q.order_by(CorpusAttribute.key)))
