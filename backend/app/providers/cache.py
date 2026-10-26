from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db.repos import cache as repo


def cache_key(key_parts: list[Any]) -> str:
    canon = json.dumps(key_parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def _label(key_parts: list[Any], i: int) -> str:
    return key_parts[i] if len(key_parts) > i and isinstance(key_parts[i], str) else ""


def cached_call(
    session: Session, key_parts: list[Any], schema: type[BaseModel] | None, fn: Callable[[], Any]
) -> Any:
    """Return the cached response for key_parts, else call fn and store it.

    Convention: key_parts[0:3] are provider, model, prompt_version (recorded on the row).
    A cached value that no longer validates against `schema` is refetched and overwritten.
    The row is flushed, not committed; the caller owns the transaction.
    """
    key = cache_key(key_parts)
    row = repo.get(session, key)
    if row is not None:
        if schema is None:
            return row.response_json
        try:
            return schema.model_validate(row.response_json)
        except ValidationError:
            pass
    result = fn()
    if schema is not None and not isinstance(result, schema):
        result = schema.model_validate(result)
    stored = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    repo.put(session, key, _label(key_parts, 0), _label(key_parts, 1), _label(key_parts, 2), stored)
    return result
