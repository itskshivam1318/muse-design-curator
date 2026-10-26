import secrets
import threading
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.db.repos import tokens as tokens_repo
from app.errors import AppError

router = APIRouter(prefix="/api/extension")

CODE_TTL_S = 600
_lock = threading.Lock()
_active: dict[str, Any] = {}  # single-user app: one pending code at a time


def _now() -> float:
    return time.time()


def reset_pair_code() -> None:
    with _lock:
        _active.clear()


class PairBody(BaseModel):
    code: str


@router.post("/pair-code")
def pair_code() -> dict[str, str]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = _now() + CODE_TTL_S
    with _lock:
        _active.clear()
        _active.update(code=code, expires=expires)
    return {"code": code, "expires_at": datetime.fromtimestamp(expires, UTC).isoformat()}


@router.post("/pair")
def pair(body: PairBody, session: SessionDep) -> dict[str, str]:
    with _lock:
        ok = (
            bool(_active)
            and _now() <= _active["expires"]
            and secrets.compare_digest(_active["code"], body.code.strip())
        )
        if ok:
            _active.clear()
    if not ok:
        raise AppError(400, "PAIR_CODE_INVALID", "That code is wrong or has expired")
    token = secrets.token_urlsafe(32)
    tokens_repo.add(session, token)
    return {"token": token}


def _check_token(request: Request, session: Session) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or not tokens_repo.verify(session, token.strip()):
        raise AppError(401, "EXTENSION_UNAUTHORIZED", "Pair the extension with your board first")


def require_extension_token(request: Request, session: SessionDep) -> None:
    """Dependency for capture requests: Authorization: Bearer <token>."""
    _check_token(request, session)


ExtensionAuth = Annotated[None, Depends(require_extension_token)]
