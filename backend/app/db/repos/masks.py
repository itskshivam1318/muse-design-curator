from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import PartMask


def get(session: Session, image_sha256: str, sam_prompt: str) -> PartMask | None:
    return session.get(PartMask, (image_sha256, sam_prompt))


def save(session: Session, image_sha256: str, sam_prompt: str, **fields: Any) -> PartMask:
    """Insert or update one cached mask row (flushed, not committed).

    Another connection (a run, a deepen job) may cache the same (image, prompt) at the same time:
    the losing insert updates the row the other one wrote.
    """
    key = (image_sha256, sam_prompt)
    row = session.get(PartMask, key)
    if row is None:
        try:
            with session.begin_nested():
                session.add(PartMask(image_sha256=image_sha256, sam_prompt=sam_prompt, **fields))
            return session.get(PartMask, key)  # type: ignore[return-value]
        except IntegrityError:
            row = session.get(PartMask, key, populate_existing=True)
            if row is None:  # pragma: no cover - the other writer's row vanished again
                raise
    for k, v in fields.items():
        setattr(row, k, v)
    session.flush()
    return row
