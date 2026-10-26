from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PartMask


def get(session: Session, image_sha256: str, sam_prompt: str) -> PartMask | None:
    return session.get(PartMask, (image_sha256, sam_prompt))


def save(session: Session, image_sha256: str, sam_prompt: str, **fields: Any) -> PartMask:
    row = session.get(PartMask, (image_sha256, sam_prompt))
    if row is None:
        row = PartMask(image_sha256=image_sha256, sam_prompt=sam_prompt, **fields)
        session.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    session.flush()
    return row
