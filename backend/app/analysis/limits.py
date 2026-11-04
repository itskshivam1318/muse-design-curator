"""Per-board daily caps on model work: item analysis and image rendering.

Counted on the demo guard's sliding windows, so the same clock and reset apply."""

from typing import Literal

from app import demo
from app.config import Settings, get_settings
from app.errors import AppError

Kind = Literal["analyse", "render", "mesh", "video"]


def _key(board_id: str, kind: Kind) -> str:
    return f"{kind}:{board_id}"


def _limit(kind: Kind, st: Settings) -> int:
    return {
        "analyse": st.ANALYSE_PER_BOARD_PER_DAY,
        "render": st.RENDER_PER_BOARD_PER_DAY,
        "mesh": st.MESH_PER_BOARD_PER_DAY,
        "video": st.VIDEO_PER_BOARD_PER_DAY,
    }[kind]


def check_and_count(board_id: str, kind: Kind, settings: Settings | None = None) -> None:
    """Take one slot of the board's daily allowance, or raise 429 DAILY_LIMIT."""
    st = settings or get_settings()
    key = _key(board_id, kind)
    retry = demo.windows.retry_after(key, demo.DAY_S, _limit(kind, st))
    if retry is not None:
        raise AppError(
            429, "DAILY_LIMIT", "Daily limit reached for this board, try tomorrow.",
            {"retry_after_s": retry},
        )  # fmt: skip
    demo.windows.add(key)


def refund(board_id: str, kind: Kind) -> None:
    """Give the slot back: the work failed before any model was called, or (put into) the
    model call itself failed and the person got nothing."""
    demo.windows.remove_last(_key(board_id, kind))


__all__ = ["check_and_count", "refund"]
