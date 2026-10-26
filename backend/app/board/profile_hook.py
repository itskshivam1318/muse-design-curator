"""Debounced profile recompute, requested whenever a board's attributes or items change."""

import logging
import threading

from app.config import get_settings

log = logging.getLogger(__name__)
DEBOUNCE_SECONDS = 1.0
_lock = threading.Lock()
_timers: dict[str, threading.Timer] = {}


def _run_recompute(board_id: str) -> None:
    from app.api import deps
    from app.board.profile import recompute

    with _lock:
        _timers.pop(board_id, None)
    session = deps.new_session()
    try:
        recompute(session, board_id)
        session.commit()
    except Exception:
        session.rollback()
        log.exception("profile recompute failed for %s", board_id)
    finally:
        session.close()


def request_recompute(board_id: str) -> None:
    """Recompute the board's profile: inline under JOBS_SYNC, else once after a 1 s quiet period."""
    if get_settings().JOBS_SYNC:
        _run_recompute(board_id)
        return
    with _lock:
        old = _timers.pop(board_id, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(DEBOUNCE_SECONDS, _run_recompute, args=(board_id,))
        timer.daemon = True
        _timers[board_id] = timer
        timer.start()
