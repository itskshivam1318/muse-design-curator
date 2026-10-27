import threading
from datetime import UTC, datetime

from ulid import ULID

PREFIXES = {
    "board": "brd_", "item": "itm_", "frame": "frm_", "attribute": "att_", "event": "evt_",
    "lens": "lens_", "corpus": "cx_", "run": "run_", "candidate": "cand_",
    "validation": "val_", "decision": "dec_", "exploration": "exp_", "option": "opt_",
}  # fmt: skip


_lock = threading.Lock()
_last = ULID.from_int(0)


def new_id(prefix: str) -> str:
    """Strictly monotonic ULIDs, so id order equals creation order within a process."""
    global _last
    with _lock:
        nxt = ULID()
        if int(nxt) <= int(_last):
            nxt = ULID.from_int(int(_last) + 1)
        _last = nxt
    return f"{prefix}{str(nxt).lower()}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
