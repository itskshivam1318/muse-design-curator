"""In-process pub/sub keyed by board id. Thread-safe; SSE transport arrives in a later task."""

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

    def close(self) -> None:
        with _lock:
            _subs[self.board_id].discard(self)
            if not _subs[self.board_id]:
                _subs.pop(self.board_id, None)
        self._closed = True
        self._q.put(None)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


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
        s._q.put({"type": type, "board_id": board_id, "data": data, "seq": seq})


def last_seq(board_id: str) -> int:
    """The sequence number of the board's most recent event (0 if none yet)."""
    with _lock:
        return _seq.get(board_id, 0)
