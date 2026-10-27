"""Live search of licensed open sources (Commons, Openverse, Met, AIC, Smithsonian).

Sources x queries fan out on a thread pool under one wall-clock deadline. A source that fails or
runs out of time is recorded and skipped; what it had already returned is kept. Results are
de-duplicated, filtered through the same provenance gate as the corpus, and capped.

A source that refuses us (HTTP 401, 403 or 429) or times out twice in a row cools down: for
LIVE_SOURCE_COOLDOWN_S it is not asked at all and reports status `skipped` (in this process only).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.corpus.provenance import check_provenance
from app.corpus.sources import SOURCES
from app.corpus.sources.base import ManifestItem, Source
from app.db.models import CorpusItem

log = logging.getLogger(__name__)
_clock = time.monotonic  # the cooldown clock (tests replace it)

# Licensed APIs only. Pexels stays disabled; no web or image search engines.
LIVE_ALLOWED = ("commons", "openverse", "met", "aic", "smithsonian")
MAX_WORKERS = 16

DISPLAY_NAMES = {
    "commons": "Wikimedia Commons", "openverse": "Openverse", "met": "the Met",
    "aic": "the Art Institute of Chicago", "smithsonian": "the Smithsonian",
}  # fmt: skip

SourceFactory = Callable[[str, str], Source]


@dataclass
class SourceStatus:
    name: str
    status: str = "ok"  # ok | failed | timeout | skipped (cooling down)
    error_code: str | None = None
    found: int = 0


class LiveItems(list[ManifestItem]):
    """The surviving items plus per-source status and drop counts."""

    def __init__(self, items: list[ManifestItem] | None = None) -> None:
        super().__init__(items or [])
        self.sources: dict[str, SourceStatus] = {}
        self.dropped: dict[str, int] = {"provenance": 0, "known": 0, "cap": 0}

    def failed(self) -> list[dict[str, str | None]]:
        return [
            {"source": s.name, "error_code": s.error_code}
            for s in self.sources.values()
            if s.status == "failed"
        ]


# ---- cooldown ----

COOL_CODES = ("HTTP_401", "HTTP_403", "HTTP_429")
TIMEOUTS_TO_COOL = 2
COOLING_DOWN = "COOLING_DOWN"


@dataclass
class _Health:
    timeouts: int = 0  # timeouts in a row
    until: float = 0.0  # cooling down until this `_clock()` instant


_health: dict[str, _Health] = {}
_health_lock = threading.Lock()


def reset_cooldowns() -> None:
    with _health_lock:
        _health.clear()


def cooling_down(name: str) -> bool:
    with _health_lock:
        h = _health.get(name)
        return h is not None and _clock() < h.until


def _record(st: SourceStatus, cooldown_s: float) -> None:
    """Update a searched source's health from this search's outcome."""
    timed_out = st.status == "timeout" or (st.status == "failed" and st.error_code == "TIMEOUT")
    with _health_lock:
        h = _health.setdefault(st.name, _Health())
        h.timeouts = h.timeouts + 1 if timed_out else 0
        refused = st.status == "failed" and st.error_code in COOL_CODES
        if cooldown_s > 0 and (refused or h.timeouts >= TIMEOUTS_TO_COOL):
            h.until = _clock() + cooldown_s
            h.timeouts = 0
            log.warning(
                "live source %s cools down for %.0f s (%s)", st.name, cooldown_s,
                st.error_code or st.status,
            )  # fmt: skip


def parse_sources(value: str) -> list[str]:
    out: list[str] = []
    for name in (n.strip().lower() for n in value.split(",")):
        if name in LIVE_ALLOWED and name not in out:
            out.append(name)
    return out


def make_source(name: str, domain: str) -> Source:
    if name not in LIVE_ALLOWED:
        raise ValueError(f"{name!r} is not a live source")
    return SOURCES[name](domain)  # type: ignore[return-value]


def error_code(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP_{exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "TIMEOUT"
    return type(exc).__name__


def _known(session: Session, items: list[ManifestItem]) -> tuple[set[str], set[str]]:
    """Ids and landing URLs of corpus rows that need no work (indexed or provenance-invalid)."""
    if not items:
        return set(), set()
    ids = {i.id for i in items}
    urls = {i.landing_url for i in items}
    q = select(CorpusItem.id, CorpusItem.landing_url, CorpusItem.indexing_status).where(
        CorpusItem.id.in_(ids) | CorpusItem.landing_url.in_(urls)
    )
    known_ids: set[str] = set()
    known_urls: set[str] = set()
    for cid, url, status in session.execute(q):
        if status == "indexed":  # pending / failed rows are retried by the quick index
            known_ids.add(cid)
            known_urls.add(url)
    return known_ids, known_urls


def known_in_corpus(session: Session) -> tuple[set[str], set[str]]:
    """Ids and landing URLs of every indexed corpus row (a snapshot for `known=`)."""
    q = select(CorpusItem.id, CorpusItem.landing_url).where(CorpusItem.indexing_status == "indexed")
    rows = session.execute(q).all()
    return {r[0] for r in rows}, {r[1] for r in rows}


def _limit_for(limits: int | Mapping[str, int], name: str) -> int:
    if isinstance(limits, int):
        return limits
    return int(limits.get(name, get_settings().LIVE_PER_SOURCE_LIMIT))


def search_live(
    queries: list[str],
    domain: str,
    sources: list[str],
    limits: int | Mapping[str, int],
    timeout: float,
    *,
    session: Session | None = None,
    known: tuple[set[str], set[str]] | None = None,
    max_candidates: int | None = None,
    source_factory: SourceFactory | None = None,
) -> LiveItems:
    """Candidates from every source for every query, de-duplicated, licence-checked, capped."""
    settings = get_settings()
    cap = settings.LIVE_MAX_CANDIDATES if max_candidates is None else max_candidates
    factory = source_factory or make_source
    listed = [n for n in sources if n in LIVE_ALLOWED] if source_factory is None else list(sources)
    result = LiveItems()
    status = {n: SourceStatus(n) for n in listed}
    result.sources = status
    names = []
    for n in listed:
        if cooling_down(n):
            status[n].status, status[n].error_code = "skipped", COOLING_DOWN
        else:
            names.append(n)
    if not names or not queries:
        return result

    stop = threading.Event()
    tasks: list[tuple[str, str, list[ManifestItem]]] = []  # (source, query, items so far)
    errors: dict[int, str] = {}

    def work(idx: int) -> None:
        name, query, out = tasks[idx]
        try:
            src = factory(name, domain)
            it = iter(src.search(query, _limit_for(limits, name)))
            try:
                for item in it:
                    out.append(item)
                    if stop.is_set():
                        return
            finally:
                close = getattr(it, "close", None)
                if close:
                    close()
        except Exception as exc:  # noqa: BLE001 - one bad source must not fail the run
            errors[idx] = error_code(exc)
            log.warning("live source %s failed: %s", name, exc)

    for name in names:
        for q in queries:
            tasks.append((name, q, []))
    pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tasks)), thread_name_prefix="live")
    futures = [pool.submit(work, i) for i in range(len(tasks))]
    deadline = time.monotonic() + timeout
    _done, pending = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
    stop.set()
    pool.shutdown(wait=False, cancel_futures=True)
    unfinished = {i for i, f in enumerate(futures) if f in pending}

    per_source: dict[str, list[ManifestItem]] = {n: [] for n in names}
    for i, (name, _q, out) in enumerate(tasks):
        per_source[name].extend(list(out))
    for name in names:
        idxs = [i for i, t in enumerate(tasks) if t[0] == name]
        ok_any = any(i not in errors and i not in unfinished for i in idxs)
        failed = [errors[i] for i in idxs if i in errors]
        if any(i in unfinished for i in idxs):
            status[name].status = "timeout"
        elif failed and not ok_any:
            status[name].status = "failed"
        if failed:
            status[name].error_code = failed[0]
        _record(status[name], settings.LIVE_SOURCE_COOLDOWN_S)

    # de-duplicate within the batch, then against the corpus, then the licence gate
    seen: set[str] = set()
    unique: dict[str, list[ManifestItem]] = {n: [] for n in names}
    for name in names:
        for item in per_source[name]:
            if item.id in seen:
                continue
            seen.add(item.id)
            unique[name].append(item)
    flat = [i for n in names for i in unique[n]]
    if known is not None:
        known_ids, known_urls = known
    elif session is not None:
        known_ids, known_urls = _known(session, flat)
    else:
        known_ids, known_urls = set(), set()
    kept: dict[str, list[ManifestItem]] = {n: [] for n in names}
    for name in names:
        for item in unique[name]:
            if item.id in known_ids or item.landing_url in known_urls:
                result.dropped["known"] += 1
                continue
            if check_provenance(item)[0] != "valid":
                result.dropped["provenance"] += 1
                continue
            kept[name].append(item)
            status[name].found += 1

    # round-robin across sources so one chatty source cannot fill the cap
    longest = max((len(v) for v in kept.values()), default=0)
    for rank in range(longest):
        for name in names:
            if rank < len(kept[name]):
                if len(result) < cap:
                    result.append(kept[name][rank])
                else:
                    result.dropped["cap"] += 1
    return result


def source_message(sources: Mapping[str, Any]) -> list[str]:
    """Plain names of sources that did not answer, for the run summary."""
    out = []
    for name, st in sources.items():
        state = st.get("status") if isinstance(st, dict) else getattr(st, "status", "ok")
        if state in ("failed", "timeout"):
            out.append(DISPLAY_NAMES.get(name, name))
    return out
