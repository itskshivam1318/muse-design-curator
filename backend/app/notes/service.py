"""Create and edit notes, and read them back as context for reasoning prompts."""

from functools import partial

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.api.schemas import item_to_dict
from app.db.models import BoardItem
from app.db.repos import items as items_repo
from app.db.session import after_commit
from app.errors import AppError
from app.ingest.common import ItemMeta, create_item

NOTE_W = 220
NOTE_H = 150
MAX_NOTES = 20
MAX_CHARS = 2000


def create_note(
    session: Session,
    board_id: str,
    text: str,
    x: float,
    y: float,
    w: float | None = None,
    h: float | None = None,
) -> BoardItem:
    """Add a note to the board; announced as item.added after the commit."""
    item = create_item(
        session, board_id, ItemMeta(origin="note", x=x, y=y),
        kind="note", rights_status="user_supplied", parse_status="completed",
        note_text=text, w=w if w is not None else NOTE_W, h=h if h is not None else NOTE_H,
    )  # fmt: skip
    after_commit(session, partial(events.publish, board_id, "item.added", item_to_dict(item)))
    return item


def set_note_text(session: Session, item_id: str, text: str) -> BoardItem:
    """Replace a note's text (no event: the caller announces the change)."""
    item = items_repo.get(session, item_id)
    if item is None or item.removed_at is not None:
        raise AppError(404, "ITEM_NOT_FOUND", "Item not found")
    if item.kind != "note":
        raise AppError(400, "NOT_A_NOTE", "Only a note has text to edit")
    item.note_text = text
    session.flush()
    return item


def update_note_text(session: Session, item_id: str, text: str) -> BoardItem:
    item = set_note_text(session, item_id, text)
    after_commit(
        session, partial(events.publish, item.board_id, "item.updated", item_to_dict(item))
    )
    return item


def board_notes_context(
    session: Session, board_id: str, max_notes: int = MAX_NOTES, max_chars: int = MAX_CHARS
) -> list[str]:
    """The board's note texts, newest first, within max_notes and max_chars in total."""
    rows = session.scalars(
        select(BoardItem.note_text)
        .where(
            BoardItem.board_id == board_id,
            BoardItem.kind == "note",
            BoardItem.removed_at.is_(None),
        )
        .order_by(BoardItem.id.desc())
    )
    out: list[str] = []
    left = max_chars
    for raw in rows:
        text = (raw or "").strip()
        if not text:
            continue
        out.append(text[:left])
        left -= len(out[-1])
        if len(out) >= max_notes or left <= 0:
            break
    return out


def notes_block(session: Session, board_id: str) -> str:
    """The notes as a prompt block, or "" when the board has none."""
    notes = board_notes_context(session, board_id)
    return "Notes on the board:\n" + "\n".join(f"- {n}" for n in notes) if notes else ""


def with_notes(session: Session, board_id: str, context: str) -> str:
    """Board context followed by its notes block."""
    return "\n\n".join(p for p in (context.strip(), notes_block(session, board_id)) if p)
