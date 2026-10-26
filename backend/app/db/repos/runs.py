from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RunCandidate, ValidationResult, VariationRun


def create(session: Session, **fields: Any) -> VariationRun:
    run = VariationRun(**fields)
    session.add(run)
    session.flush()
    return run


def get(session: Session, run_id: str) -> VariationRun | None:
    return session.get(VariationRun, run_id)


def by_idempotency_key(session: Session, key: str) -> VariationRun | None:
    return session.scalar(select(VariationRun).where(VariationRun.idempotency_key == key))


def update(session: Session, run_id: str, **fields: Any) -> VariationRun | None:
    run = session.get(VariationRun, run_id)
    if run is None:
        return None
    for k, v in fields.items():
        setattr(run, k, v)
    session.flush()
    return run


def add_candidate(session: Session, **fields: Any) -> RunCandidate:
    cand = RunCandidate(**fields)
    session.add(cand)
    session.flush()
    return cand


def get_candidate(session: Session, candidate_id: str) -> RunCandidate | None:
    return session.get(RunCandidate, candidate_id)


def update_candidate(session: Session, candidate_id: str, **fields: Any) -> RunCandidate | None:
    cand = session.get(RunCandidate, candidate_id)
    if cand is None:
        return None
    for k, v in fields.items():
        setattr(cand, k, v)
    session.flush()
    return cand


def candidates(session: Session, run_id: str) -> list[RunCandidate]:
    q = select(RunCandidate).where(RunCandidate.run_id == run_id)
    return list(session.scalars(q.order_by(RunCandidate.rank.is_(None), RunCandidate.rank)))


def add_validation(session: Session, **fields: Any) -> ValidationResult:
    row = ValidationResult(**fields)
    session.add(row)
    session.flush()
    return row


def validations(session: Session, run_candidate_id: str) -> list[ValidationResult]:
    q = select(ValidationResult).where(ValidationResult.run_candidate_id == run_candidate_id)
    return list(session.scalars(q.order_by(ValidationResult.id)))
