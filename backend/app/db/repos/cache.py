from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ModelCache


def get(session: Session, key: str) -> ModelCache | None:
    return session.get(ModelCache, key)


def put(
    session: Session, key: str, provider: str, model: str, prompt_version: str, response: Any
) -> ModelCache:
    row = session.get(ModelCache, key)
    if row is None:
        row = ModelCache(key=key, provider=provider, model=model, prompt_version=prompt_version,
                         response_json=response)  # fmt: skip
        session.add(row)
    else:
        row.response_json = response
    session.flush()
    return row
