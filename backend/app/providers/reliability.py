"""Error taxonomy, timeout and retry helpers shared by every provider."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import httpx
import openai

CODES = frozenset({
    "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_RATE_LIMITED", "MODEL_INVALID_RESPONSE",
    "GATEWAY_TIMEOUT", "PAYLOAD_TOO_LARGE", "BILLING_NOT_CONFIGURED", "TOO_MANY_IMAGES",
    "PROVIDER_MISCONFIGURED",
})  # fmt: skip
RETRYABLE = frozenset({"MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_RATE_LIMITED"})


class ModelError(Exception):
    def __init__(self, code: str, retry_after: float | None = None, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.retry_after = retry_after
        self.message = message or code


def _retry_after(headers: Any) -> float | None:
    raw = headers.get("retry-after") if headers is not None else None
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def map_exception(exc: BaseException) -> ModelError:
    """Translate SDK / transport exceptions into ModelError."""
    if isinstance(exc, ModelError):
        return exc
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return ModelError("MODEL_TIMEOUT", message=str(exc))
    if isinstance(exc, openai.APIStatusError):
        s = exc.status_code
        msg = str(exc)
        if s == 429:
            return ModelError("MODEL_RATE_LIMITED", _retry_after(exc.response.headers), msg)
        if s == 504:
            return ModelError("GATEWAY_TIMEOUT", message=msg)
        if s >= 500:
            return ModelError("MODEL_UNAVAILABLE", message=msg)
        if s == 413:
            return ModelError("PAYLOAD_TOO_LARGE", message=msg)
        if s == 402:
            return ModelError("BILLING_NOT_CONFIGURED", message=msg)
        if s in (401, 403):
            return ModelError("PROVIDER_MISCONFIGURED", message=msg)
        return ModelError("MODEL_INVALID_RESPONSE", message=msg)
    if isinstance(exc, (openai.APIConnectionError, httpx.TransportError)):
        return ModelError("MODEL_UNAVAILABLE", message=str(exc))
    return ModelError("MODEL_INVALID_RESPONSE", message=f"{type(exc).__name__}: {exc}")


def with_timeout[T](fn: Callable[[], T], seconds: float) -> T:
    """Run fn in a worker thread; raise MODEL_TIMEOUT if it does not finish in time."""
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except FutureTimeout:
        raise ModelError("MODEL_TIMEOUT", message=f"no response within {seconds}s") from None
    finally:
        pool.shutdown(wait=False)


def with_retry[T](fn: Callable[[], T], max_retries: int = 2, base_delay: float = 0.25) -> T:
    """Retry TIMEOUT / UNAVAILABLE / RATE_LIMITED only; every other error propagates at once."""
    attempt = 0
    while True:
        try:
            return fn()
        except ModelError as err:
            if err.code not in RETRYABLE or attempt >= max_retries:
                raise
            delay = err.retry_after if err.retry_after is not None else base_delay * 2**attempt
            time.sleep(delay)
            attempt += 1


def call_model[T](fn: Callable[[], T], *, timeout: float, max_retries: int) -> T:
    """Timeout + exception mapping + retry around one provider call."""

    def once() -> T:
        try:
            return with_timeout(fn, timeout)
        except ModelError:
            raise
        except Exception as exc:
            raise map_exception(exc) from exc

    return with_retry(once, max_retries=max_retries)
