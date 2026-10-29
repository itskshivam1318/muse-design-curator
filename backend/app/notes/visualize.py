"""Visualize a note: generate an image from its text, place it beside the note, parse and check it.

The request claims the note (a timestamp in its `generation_json`) and queues the job. A failure
before the image exists leaves no item and frees the claim; after that the item stays and a parse
or check failure is stored on it. The image lands on the canvas directly (not staged).
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import events, jobs
from app.api.schemas import item_to_dict
from app.config import get_settings
from app.db.models import Board, BoardItem
from app.db.repos import items as items_repo
from app.db.session import after_commit
from app.errors import AppError
from app.explore.check import check_target_only
from app.explore.visualize import CLAIM_TTL_S, IMAGE_GAP, STACK_GAP, _iso, _stamped
from app.extraction.service import _image_for, _require_item, parse_item
from app.ingest.common import ItemMeta, create_item, default_size
from app.ingest.images import decode_image
from app.providers import get_image_provider
from app.providers.reliability import ModelError
from app.storage import files

log = logging.getLogger(__name__)

JOB = "visualize_note"
CLAIM_KEY = "visualizing_since"


def note_prompt(note_text: str, board_title: str, board_context: str | None) -> str:
    """The note's text plus a short board line (left out when the board has neither)."""
    title, context = (board_title or "").strip(), (board_context or "").strip()
    board = " — ".join(p for p in (title, context) if p)
    note = note_text.strip().rstrip(".")
    parts = [note, *([f"Board: {board}"] if board else []), "Product photo, plain background"]
    return ". ".join(parts) + "."


def _note(session: Session, note_id: str) -> BoardItem:
    note = items_repo.get(session, note_id)
    if note is None or note.removed_at is not None:
        raise AppError(404, "ITEM_NOT_FOUND", "Item not found")
    if note.kind != "note":
        raise AppError(400, "NOT_A_NOTE", "Only a note can be visualized from its text")
    return note


def request_note_visualize(session: Session, note_id: str) -> None:
    """Claim the note and queue the job. 409 while it is already visualizing, unless that
    claim is older than CLAIM_TTL_S (its job died with the process)."""
    note = _note(session, note_id)
    stale = _iso(datetime.now(UTC) - timedelta(seconds=CLAIM_TTL_S))
    since = BoardItem.generation_json[CLAIM_KEY].as_string()
    claimed = session.execute(
        update(BoardItem)
        .where(BoardItem.id == note_id, or_(since.is_(None), since < stale))
        .values(generation_json={CLAIM_KEY: _iso(datetime.now(UTC))})
    )
    if not claimed.rowcount:  # type: ignore[attr-defined]
        raise AppError(409, "NOTE_VISUALIZING", "This note is already being visualized")
    after_commit(
        session, partial(events.publish, note.board_id, "note.visualizing", {"note_id": note_id})
    )
    after_commit(session, partial(jobs.enqueue, JOB, note_id=note_id))


def _ingest(session: Session, note: BoardItem, data: bytes, model: str, prompt: str) -> BoardItem:
    """Store the generated image like an upload, never deduped, beside the note and below the
    images already generated from it."""
    img = decode_image(data)
    data = _stamped(img, model, note.id)
    sha = files.sha256_hex(data)
    storage = files.save_original(data, sha, "png")
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    earlier = session.scalars(
        select(BoardItem).where(
            BoardItem.parent_item_id == note.id,
            BoardItem.origin == "generated",
            BoardItem.removed_at.is_(None),
        )
    )
    below = sum(i.h + STACK_GAP for i in earlier)
    meta = ItemMeta(
        origin="generated", filename="note.png", x=note.x + note.w + IMAGE_GAP, y=note.y + below
    )
    return create_item(
        session, note.board_id, meta,
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=img.size[0], height=img.size[1], w=w, h=h, rights_status="generated",
        parent_item_id=note.id,
        generation_json={"model": model, "prompt": prompt, "from": "note"},
    )  # fmt: skip


def _settle(session: Session, note_id: str, error: str | None, item_id: str | None = None) -> None:
    """Free the claim and announce the outcome."""
    session.execute(update(BoardItem).where(BoardItem.id == note_id).values(generation_json=None))
    note = items_repo.get(session, note_id)
    if note is None:
        return
    if error is None:
        data: dict[str, Any] = {"note_id": note_id, "item_id": item_id}
        kind = "note.visualized"
    else:
        data = {"note_id": note_id, "error": error}
        kind = "note.visualize_failed"
    after_commit(session, partial(events.publish, note.board_id, kind, data))


def _check(session: Session, item_id: str, note_text: str) -> dict[str, Any]:
    """Parse the new item, then check it against the note; a failure is stored as {"error"}."""
    try:
        parse_item(session, item_id)  # commits; a model failure marks the item failed
    except AppError as exc:
        return {"error": exc.code}
    session.expire_all()
    item = _require_item(session, item_id)
    if item.parse_status == "failed":
        return {"error": item.parse_error_code or "PARSE_ERROR"}
    try:
        image, _sha = _image_for(session, item)
        return check_target_only(image, note_text)
    except (ModelError, AppError) as exc:
        return {"error": exc.code}
    except Exception:
        log.exception("checking generated item %s failed", item_id)
        return {"error": "CHECK_ERROR"}


def visualize(session: Session, note_id: str) -> None:
    note = items_repo.get(session, note_id)
    if note is None:
        return
    text = note.note_text or ""
    try:
        board = session.get(Board, note.board_id)
        prompt = note_prompt(text, board.title if board else "", board.context if board else "")
        provider = get_image_provider(get_settings())
        item = _ingest(session, note, provider.generate(prompt), provider.model, prompt)
    except (ModelError, AppError) as exc:
        session.rollback()
        _settle(session, note_id, exc.code)
        session.commit()
        return
    added = item_to_dict(item)
    after_commit(session, partial(events.publish, item.board_id, "item.added", added))
    session.commit()

    check = _check(session, item.id, text)
    item = _require_item(session, item.id)
    item.check_json = check
    session.flush()
    after_commit(
        session, partial(events.publish, item.board_id, "item.updated", item_to_dict(item))
    )
    _settle(session, note_id, None, item.id)
    session.commit()


def visualize_job(note_id: str) -> None:
    from app.api import deps

    with deps._factory()() as session:
        try:
            visualize(session, note_id)
        except Exception:
            session.rollback()
            log.exception("visualizing note %s failed", note_id)
            _settle(session, note_id, "VISUALIZE_ERROR")
            session.commit()


def recover_stuck_notes(session: Session) -> int:
    """Startup: no job survives a restart, so every note claim is freed; a generated item
    whose check never finished is marked INTERRUPTED. Returns the claims freed."""
    since = BoardItem.generation_json[CLAIM_KEY].as_string()
    stuck = list(
        session.scalars(select(BoardItem).where(BoardItem.kind == "note", since.is_not(None)))
    )
    for note in stuck:
        note.generation_json = None
    session.flush()
    return len(stuck)


jobs.register(JOB, visualize_job)
