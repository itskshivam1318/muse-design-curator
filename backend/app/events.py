"""In-process pub/sub keyed by board id. Thread-safe.

`subscribe` gives a blocking queue (workers, tests); `subscribe_async` gives an asyncio queue fed
with `loop.call_soon_threadsafe`, so an SSE stream awaits events without holding a worker thread.
"""

import asyncio
import contextlib
import queue
import threading
from collections import defaultdict
from typing import Any, Self

_lock = threading.Lock()
_subs: dict[str, set["Subscription"]] = defaultdict(set)
_seq: dict[str, int] = defaultdict(int)


class Subscription:
    def __init__(self, board_id: str) -> None:
        self.board_id = board_id
        self._q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._closed = False

    def get(self, timeout: float | None = None) -> dict[str, Any] | None:
        """Next event, or None on timeout/close."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def __iter__(self) -> "Subscription":
        return self

    def __next__(self) -> dict[str, Any]:
        ev = self._q.get()
        if ev is None:
            raise StopIteration
        return ev

    def _deliver(self, ev: dict[str, Any]) -> None:
        self._q.put(ev)

    def _unregister(self) -> None:
        with _lock:
            _subs[self.board_id].discard(self)
            if not _subs[self.board_id]:
                _subs.pop(self.board_id, None)
        self._closed = True

    def close(self) -> None:
        self._unregister()
        self._q.put(None)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AsyncSubscription(Subscription):
    """Delivers into an asyncio.Queue on `loop`; safe to publish from any thread."""

    def __init__(self, board_id: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(board_id)
        self._loop = loop
        self._aq: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def _deliver(self, ev: dict[str, Any]) -> None:
        with contextlib.suppress(RuntimeError):  # the loop has already closed
            self._loop.call_soon_threadsafe(self._aq.put_nowait, ev)

    async def aget(self, timeout: float) -> dict[str, Any] | None:
        """Next event, or None after `timeout` seconds."""
        try:
            return await asyncio.wait_for(self._aq.get(), timeout)
        except TimeoutError:
            return None

    def close(self) -> None:
        self._unregister()


def subscribe_async(board_id: str) -> AsyncSubscription:
    """Call from the event loop that will await the events."""
    sub = AsyncSubscription(board_id, asyncio.get_running_loop())
    with _lock:
        _subs[board_id].add(sub)
    return sub


def subscribe(board_id: str) -> Subscription:
    sub = Subscription(board_id)
    with _lock:
        _subs[board_id].add(sub)
    return sub


def publish(board_id: str, type: str, data: dict[str, Any]) -> None:
    with _lock:
        _seq[board_id] += 1
        seq = _seq[board_id]
        targets = list(_subs.get(board_id, ()))
    for s in targets:
        s._deliver({"type": type, "board_id": board_id, "data": data, "seq": seq})


def last_seq(board_id: str) -> int:
    """The sequence number of the board's most recent event (0 if none yet)."""
    with _lock:
        return _seq.get(board_id, 0)
