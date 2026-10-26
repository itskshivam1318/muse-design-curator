from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Decision


def append(session: Session, **fields: Any) -> Decision:
    row = Decision(**fields)
    session.add(row)
    session.flush()
    return row


def history(session: Session, run_candidate_id: str) -> list[Decision]:
    """Newest first; ULIDs are time-ordered so id breaks created_at ties."""
    q = select(Decision).where(Decision.run_candidate_id == run_candidate_id)
    return list(session.scalars(q.order_by(Decision.created_at.desc(), Decision.id.desc())))
