"""Tiny background job registry. JOBS_SYNC=1 runs jobs inline (tests)."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)
_registry: dict[str, Callable[..., Any]] = {}
_queue_of: dict[str, str] = {}
BACKGROUND_MAX_PENDING = 32
_pending = {"background": 0}
_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None
_bg_pool: ThreadPoolExecutor | None = None


def register(name: str, fn: Callable[..., Any], queue: str = "default") -> None:
    """`queue='background'` runs on its own single worker so bulk jobs never block the rest."""
    _registry[name] = fn
    _queue_of[name] = queue


def _run(name: str, fn: Callable[..., Any], kwargs: dict[str, Any]) -> None:
    try:
        fn(**kwargs)
    except Exception:
        log.exception("job %s failed", name)


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dle-job")
        return _pool


def _background() -> ThreadPoolExecutor:
    global _bg_pool
    with _lock:
        if _bg_pool is None:
            _bg_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dle-bg")
        return _bg_pool


def _run_background(name: str, fn: Callable[..., Any], kwargs: dict[str, Any]) -> None:
    try:
        _run(name, fn, kwargs)
    finally:
        with _lock:
            _pending["background"] -= 1


def enqueue(name: str, **kwargs: Any) -> None:
    fn = _registry.get(name)
    if fn is None:
        log.debug("job %s not registered; skipping", name)
        return
    if get_settings().JOBS_SYNC:
        _run(name, fn, kwargs)
    elif _queue_of.get(name) == "background":
        with _lock:
            if _pending["background"] >= BACKGROUND_MAX_PENDING:
                log.info("background queue full; dropping %s", name)
                return
            _pending["background"] += 1
        _background().submit(_run_background, name, fn, kwargs)
    else:
        _executor().submit(_run, name, fn, kwargs)
