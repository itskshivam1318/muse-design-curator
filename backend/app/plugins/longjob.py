"""Long paid model jobs on fal's queue, resumable across a restart.

`run_fal` takes one slot of the board's daily cap, submits once, stores the request on the run
(`PluginRun.external_json`, committed before the first poll) and polls until fal is done. A
process that dies mid-poll leaves the run `running` with its request id; at startup
`service.recover_stuck_runs` queues a resume job that runs the plugin again, and `run_fal` then
sees the stored request and only polls it (`resume`): no second submit, no second cap slot.
A paid submit is never retried.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.analysis import limits
from app.config import get_settings
from app.db.models import PluginRun
from app.explore.visualize import _iso
from app.plugins.runners import PluginError
from app.providers import get_fal
from app.providers.fal import FalClient, MockFal
from app.providers.reliability import RETRYABLE, ModelError, user_message

log = logging.getLogger(__name__)

Cap = Literal["mesh", "video"]
Payload = dict[str, Any] | Callable[[], dict[str, Any]]
_WAITING = {"IN_QUEUE": "Waiting in the model's queue", "IN_PROGRESS": "The model is working"}


def _failed(message: str) -> PluginError:
    return PluginError("PLUGIN_MODEL_FAILED", message)


def _store(session: Session, run: PluginRun, ext: dict[str, Any]) -> None:
    run.external_json = dict(ext)
    session.commit()


def run_fal(
    session: Session,
    run: PluginRun,
    endpoint: str,
    payload: Payload,
    cap: Cap,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    """fal's result dict for this run's job. `payload` may be a callable, built only when a
    submit is due (so a resume does not upload the inputs again). Raises AppError 429
    DAILY_LIMIT when the cap is spent (nothing submitted), PluginError otherwise; the slot is
    refunded on every failure of a job this call submitted."""
    ext = run.external_json or {}
    if ext.get("request_id"):
        return resume(session, run, progress)
    settings = get_settings()
    limits.check_and_count(run.board_id, cap, settings)
    try:
        fal = get_fal(settings)
        body = payload() if callable(payload) else payload
        progress("Sending to the model")
        request_id = fal.submit(endpoint, body)
    except ModelError as e:
        limits.refund(run.board_id, cap)
        raise _failed(f"the model failed: {user_message(e)}") from None
    except BaseException:
        limits.refund(run.board_id, cap)
        raise
    ext = {
        "endpoint": endpoint, "request_id": request_id, "status": "IN_QUEUE", "cap": cap,
        "submitted_at": _iso(datetime.now(UTC)),
    }  # fmt: skip
    _store(session, run, ext)
    try:
        return _poll(session, run, fal, ext, progress)
    except PluginError:
        limits.refund(run.board_id, cap)
        raise


def resume(
    session: Session, run: PluginRun, progress: Callable[[str], None] | None = None
) -> dict[str, Any]:
    """Poll the request stored on the run, without submitting. The cap slot was taken by the
    process that submitted (daily counts live in process memory), so nothing is charged or
    refunded here."""
    ext = dict(run.external_json or {})
    if not ext.get("request_id") or not ext.get("endpoint"):
        raise _failed("there is no model job to resume")
    try:
        fal = get_fal(get_settings())
    except ModelError as e:
        raise _failed(f"the model failed: {user_message(e)}") from None
    return _poll(session, run, fal, ext, progress or (lambda _m: None))


def _deadline(ext: dict[str, Any], timeout_s: float) -> float:
    try:
        start = datetime.fromisoformat(str(ext["submitted_at"])).timestamp()
    except (KeyError, ValueError):
        start = time.time()
    return start + timeout_s


def _poll(
    session: Session,
    run: PluginRun,
    fal: FalClient | MockFal,
    ext: dict[str, Any],
    progress: Callable[[str], None],
) -> dict[str, Any]:
    """Status every FAL_POLL_S until COMPLETED / FAILED / FAL_TIMEOUT_S after the submit (always
    asked at least once, so a job that finished while the server was down is still collected).
    Each wait goes through `progress`, which is the run's claim heartbeat."""
    settings = get_settings()
    endpoint, request_id = str(ext["endpoint"]), str(ext["request_id"])
    deadline = _deadline(ext, settings.FAL_TIMEOUT_S)
    while True:
        try:
            st = fal.status(endpoint, request_id)
        except ModelError as e:
            if e.code not in RETRYABLE or time.time() >= deadline:
                raise _failed(f"the model failed: {user_message(e)}") from None
            log.info("fal status for %s failed (%s); polling again", request_id, e.code)
            st = None
        if st is not None and st != ext.get("status"):
            ext["status"] = st
            _store(session, run, ext)
        if st == "COMPLETED":
            try:
                return fal.result(endpoint, request_id)
            except ModelError as e:
                raise _failed(f"the model failed: {user_message(e)}") from None
        if st == "FAILED":
            raise _failed("the model could not finish this job")
        if time.time() >= deadline:
            raise _failed(f"the model took longer than {settings.FAL_TIMEOUT_S} s")
        progress(_WAITING.get(st or "", "Waiting for the model"))
        time.sleep(settings.FAL_POLL_S)


__all__ = ["Cap", "Payload", "resume", "run_fal"]
