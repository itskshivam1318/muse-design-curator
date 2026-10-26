"""Server-sent events for a board: the latest profile first, then the live stream."""

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import events
from app.board.profile import BoardProfile
from app.db.repos import profiles as profiles_repo

POLL_SECONDS = 0.5


def profile_snapshot(session: Session, board_id: str) -> dict[str, Any]:
    row = profiles_repo.latest(session, board_id)
    if row is None:
        return {"version": 0, "profile": BoardProfile().model_dump(mode="json")}
    return {"version": row.version, "profile": row.profile_json, "computed_at": row.computed_at}


def _frame(type_: str, data: dict[str, Any], seq: int | None) -> dict[str, Any]:
    out: dict[str, Any] = {"event": type_, "data": json.dumps(data, default=str)}
    if seq is not None:
        out["id"] = str(seq)
    return out


async def stream(
    board_id: str, request: Request, session: Session
) -> AsyncIterator[dict[str, Any]]:
    """Subscribe first (no gap), send the current profile, then relay events until disconnect."""
    sub = events.subscribe(board_id)
    try:
        row = profiles_repo.latest(session, board_id)
        if row is not None:
            snap = {"version": row.version, "profile": row.profile_json}
            yield _frame("profile.updated", snap, events.last_seq(board_id))
        session.close()
        while True:
            ev = await run_in_threadpool(sub.get, POLL_SECONDS)
            if ev is not None:
                yield _frame(ev["type"], ev["data"], ev["seq"])
            elif await request.is_disconnected():
                break
    finally:
        sub.close()
