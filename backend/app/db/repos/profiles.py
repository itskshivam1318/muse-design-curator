from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BoardProfile


def save(session: Session, board_id: str, profile: Any) -> int:
    current = session.scalar(
        select(func.max(BoardProfile.version)).where(BoardProfile.board_id == board_id)
    )
    version = (current or 0) + 1
    session.add(BoardProfile(board_id=board_id, version=version, profile_json=profile))
    session.flush()
    return version


def latest(session: Session, board_id: str) -> BoardProfile | None:
    q = select(BoardProfile).where(BoardProfile.board_id == board_id)
    return session.scalar(q.order_by(BoardProfile.version.desc()).limit(1))


def history(session: Session, board_id: str) -> list[BoardProfile]:
    q = select(BoardProfile).where(BoardProfile.board_id == board_id)
    return list(session.scalars(q.order_by(BoardProfile.version.desc())))
