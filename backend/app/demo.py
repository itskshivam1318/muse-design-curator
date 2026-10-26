"""Public-demo guard (DEMO_MODE=1): read-only unless unlocked, and capped Vary runs.

Open without unlock: every GET, item position PATCHes, run creation (rate-limited) and
keep/reject decisions. Every other write needs the `dle_demo` cookie that POST /api/demo/unlock
sets after a correct passcode. With DEMO_MODE off, nothing here has any effect.

Rate-limit state is in memory (one process, as the in-process job runner already requires).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import VariationRun
from app.domain.variation import VariationRequest
from app.errors import AppError

COOKIE = "dle_demo"
COOKIE_TTL_S = 12 * 3600
UNLOCK_MAX_FAILURES, UNLOCK_WINDOW_S = 5, 600
HOUR_S, DAY_S = 3600, 86400
REPLAY_WINDOW = timedelta(hours=24)
LOCKED_MESSAGE = "This is a read-only demo. Enter the passcode to add references."

# Writes that stay open while locked (method, path). PATCH /api/items/{id} is checked again in
# the route: only position fields are open.
_OPEN_WRITES = [
    ("POST", re.compile(r"^/api/boards/[^/]+/runs$")),
    ("POST", re.compile(r"^/api/runs/[^/]+/candidates/[^/]+/decisions$")),
    ("PATCH", re.compile(r"^/api/items/[^/]+$")),
    ("POST", re.compile(r"^/api/demo/unlock$")),
]
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

now = time.time  # replaced in tests


def check_settings(settings: Settings) -> None:
    """Startup check: a demo without a passcode and signing secret must not start."""
    if settings.DEMO_MODE and not (settings.DEMO_SECRET and settings.DEMO_PASSCODE):
        raise RuntimeError("DEMO_MODE=1 requires DEMO_PASSCODE and DEMO_SECRET")


# ---- unlock cookie ----


def _sign(secret: str, expiry: int) -> str:
    return hmac.new(secret.encode(), str(expiry).encode(), hashlib.sha256).hexdigest()


def make_cookie(secret: str, expiry: int) -> str:
    return f"{expiry}.{_sign(secret, expiry)}"


def cookie_valid(secret: str, value: str | None) -> bool:
    if not value or "." not in value:
        return False
    raw_expiry, sig = value.split(".", 1)
    try:
        expiry = int(raw_expiry)
    except ValueError:
        return False
    # bytes, not str: compare_digest raises TypeError on non-ASCII str (a crafted cookie)
    expected = _sign(secret, expiry).encode()
    return hmac.compare_digest(sig.encode("utf-8", "surrogateescape"), expected) and expiry > now()


def is_unlocked(request: Request, settings: Settings | None = None) -> bool:
    st = settings or get_settings()
    if not st.DEMO_MODE:
        return True
    return cookie_valid(st.DEMO_SECRET or "", request.cookies.get(COOKIE))


def require_unlocked(request: Request) -> None:
    if not is_unlocked(request):
        raise AppError(403, "DEMO_LOCKED", LOCKED_MESSAGE)


def write_is_open(method: str, path: str) -> bool:
    if method in _SAFE_METHODS:
        return True
    return any(m == method and rx.match(path) for m, rx in _OPEN_WRITES)


def client_ip(request: Request, settings: Settings | None = None) -> str:
    st = settings or get_settings()
    if st.DEMO_TRUST_PROXY and st.DEMO_PROXY_HOPS >= 1:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if len(hops) >= st.DEMO_PROXY_HOPS:
            return hops[-st.DEMO_PROXY_HOPS]
    return request.client.host if request.client else "unknown"


def is_https(request: Request, settings: Settings | None = None) -> bool:
    st = settings or get_settings()
    if st.DEMO_TRUST_PROXY:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        if proto:
            return proto == "https"
    return request.url.scheme == "https"


# ---- sliding windows ----


class _Windows:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def _trim(self, key: str, window: float) -> deque[float]:
        q = self._hits.setdefault(key, deque())
        cutoff = now() - window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def retry_after(self, key: str, window: float, limit: int) -> int | None:
        """Seconds until a slot frees up, or None when under the limit."""
        with self._lock:
            q = self._trim(key, window)
            if len(q) < limit:
                return None
            return max(1, int(q[0] + window - now()) + 1)

    def add(self, key: str) -> None:
        with self._lock:
            self._hits.setdefault(key, deque()).append(now())

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


windows = _Windows()


def reset() -> None:
    windows.clear()


def _when(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds / 3600)} hours"


def _limited(message: str, retry: int) -> AppError:
    return AppError(
        429, "DEMO_RATE_LIMITED", f"{message} Try again in {_when(retry)}.",
        {"retry_after_s": retry},
    )  # fmt: skip


# ---- unlock attempts ----


def check_unlock_attempts(ip: str) -> None:
    retry = windows.retry_after(f"unlock:{ip}", UNLOCK_WINDOW_S, UNLOCK_MAX_FAILURES)
    if retry is not None:
        raise _limited("Too many wrong passcodes.", retry)


def record_unlock_failure(ip: str) -> None:
    windows.add(f"unlock:{ip}")


def passcode_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


# ---- Vary runs ----


def check_run_limits(ip: str, settings: Settings | None = None) -> None:
    st = settings or get_settings()
    retry = windows.retry_after(f"run:{ip}", HOUR_S, st.DEMO_RUNS_PER_IP_PER_HOUR)
    if retry is not None:
        raise _limited(
            f"Demo limit reached: {st.DEMO_RUNS_PER_IP_PER_HOUR} Vary runs per hour.", retry
        )
    retry = windows.retry_after("run:*", DAY_S, st.DEMO_RUNS_PER_DAY)
    if retry is not None:
        raise _limited(
            f"The demo's daily limit of {st.DEMO_RUNS_PER_DAY} Vary runs is used up.", retry
        )


def record_run(ip: str) -> None:
    windows.add(f"run:{ip}")
    windows.add("run:*")


def _canonical(
    target_key: str, mode: str, values: Any, nudge: Any, protected: Any
) -> tuple[Any, ...]:
    nudge_t = (nudge or {}).get("direction"), (nudge or {}).get("steps")
    return (
        target_key,
        mode,
        tuple(sorted(map(str, values or []))),
        nudge_t,
        tuple(sorted(protected or [])),
    )


def replayable_run(session: Session, board_id: str, req: VariationRequest) -> VariationRun | None:
    """A completed run of the same request on the same board and source in the last 24 h."""
    want = _canonical(
        req.target_key, req.mode, req.target_values,
        req.nudge.model_dump() if req.nudge else None, req.protected_keys,
    )  # fmt: skip
    cutoff = datetime.fromtimestamp(now(), UTC) - REPLAY_WINDOW
    q = (
        select(VariationRun)
        .where(
            VariationRun.board_id == board_id,
            VariationRun.source_item_id == req.source_item_id,
            VariationRun.status == "completed",
        )
        .order_by(VariationRun.created_at.desc())
    )
    for run in session.scalars(q):
        if datetime.fromisoformat(run.created_at) < cutoff:
            break
        have = _canonical(
            run.target_key, run.mode, run.target_values_json, run.nudge_json,
            run.protected_keys_json,
        )  # fmt: skip
        if have == want:
            return run
    return None
