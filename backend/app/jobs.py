"""Tiny background job registry. JOBS_SYNC=1 runs jobs inline (tests)."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)
_registry: dict[str, Callable[..., Any]] = {}
_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None


def register(name: str, fn: Callable[..., Any]) -> None:
    _registry[name] = fn


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


def enqueue(name: str, **kwargs: Any) -> None:
    fn = _registry.get(name)
    if fn is None:
        log.debug("job %s not registered; skipping", name)
        return
    if get_settings().JOBS_SYNC:
        _run(name, fn, kwargs)
    else:
        _executor().submit(_run, name, fn, kwargs)
