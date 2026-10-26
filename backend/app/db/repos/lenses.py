from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Lens


def _scope(board_id: str | None, domain: str) -> list[Any]:
    cond = Lens.board_id.is_(None) if board_id is None else Lens.board_id == board_id
    return [cond, Lens.domain == domain]


def save(
    session: Session,
    board_id: str | None,
    domain: str,
    origin: str,
    spec: Any,
    status: str = "proposed",
) -> Lens:
    """Lenses are immutable: every save is a new row with the next version."""
    current = session.scalar(select(func.max(Lens.version)).where(*_scope(board_id, domain)))
    lens = Lens(
        board_id=board_id,
        domain=domain,
        version=(current or 0) + 1,
        origin=origin,
        status=status,
        spec_json=spec,
    )
    session.add(lens)
    session.flush()
    return lens


def get(session: Session, lens_id: str) -> Lens | None:
    return session.get(Lens, lens_id)


def latest(session: Session, board_id: str | None, domain: str) -> Lens | None:
    q = select(Lens).where(*_scope(board_id, domain)).order_by(Lens.version.desc()).limit(1)
    return session.scalar(q)


def versions(session: Session, board_id: str | None, domain: str) -> list[Lens]:
    return list(
        session.scalars(select(Lens).where(*_scope(board_id, domain)).order_by(Lens.version))
    )
