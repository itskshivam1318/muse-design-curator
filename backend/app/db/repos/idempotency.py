from typing import Any

from sqlalchemy.orm import Session

from app.db.models import IdempotencyKey


def get(session: Session, key: str) -> IdempotencyKey | None:
    return session.get(IdempotencyKey, key)


def put(
    session: Session, key: str, route: str, request_hash: str, status_code: int, response: Any
) -> IdempotencyKey:
    row = IdempotencyKey(key=key, route=route, request_hash=request_hash,
                         status_code=status_code, response_json=response)  # fmt: skip
    session.add(row)
    session.flush()
    return row
