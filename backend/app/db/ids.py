from datetime import UTC, datetime

from ulid import ULID

PREFIXES = {
    "board": "brd_", "item": "itm_", "frame": "frm_", "attribute": "att_", "event": "evt_",
    "lens": "lens_", "corpus": "cx_", "run": "run_", "candidate": "cand_",
    "validation": "val_", "decision": "dec_",
}  # fmt: skip


def new_id(prefix: str) -> str:
    return f"{prefix}{str(ULID()).lower()}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
