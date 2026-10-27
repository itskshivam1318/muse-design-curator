"""Server-sent events for a board: the latest profile first, then the live stream."""

import json
import threading
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app import events
from app.board.profile import BoardProfile
from app.db.repos import profiles as profiles_repo
from app.errors import AppError

POLL_SECONDS = 0.5
MAX_STREAMS_PER_IP = 3
MAX_STREAMS_TOTAL = 50

_slots_lock = threading.Lock()
_open: Counter[str] = Counter()


class StreamSlot:
    """One open SSE stream counted against the per-IP and global caps; release is idempotent."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        self._released = False

    def release(self) -> None:
        with _slots_lock:
            if self._released:
                return
            self._released = True
            _open[self.ip] -= 1
            if _open[self.ip] <= 0:
                del _open[self.ip]


def acquire_slot(ip: str) -> StreamSlot:
    with _slots_lock:
        if _open[ip] >= MAX_STREAMS_PER_IP or sum(_open.values()) >= MAX_STREAMS_TOTAL:
            if not _open[ip]:
                del _open[ip]
            raise AppError(
                429, "TOO_MANY_STREAMS",
                "Too many live connections are open; close another tab and try again",
            )  # fmt: skip
        _open[ip] += 1
    return StreamSlot(ip)


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
    board_id: str, request: Request, session: Session, slot: StreamSlot | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Subscribe first (no gap), send the current profile, then relay events until disconnect.

    Awaits an asyncio queue, so an open stream never holds a threadpool worker.
    """
    sub = events.subscribe_async(board_id)
    try:
        row = profiles_repo.latest(session, board_id)
        if row is not None:
            snap = {"version": row.version, "profile": row.profile_json}
            yield _frame("profile.updated", snap, events.last_seq(board_id))
        session.close()
        while True:
            ev = await sub.aget(POLL_SECONDS)
            if ev is not None:
                yield _frame(ev["type"], ev["data"], ev["seq"])
            elif await request.is_disconnected():
                break
    finally:
        sub.close()
        if slot is not None:
            slot.release()
