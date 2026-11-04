"""Render view: the same design drawn again from another viewpoint.

The request checks the anchor picture, takes a render slot and queues the job; it answers
with where the result will land. The job sends the whole picture to the image model with a
view prompt and adds the result to the board as a generated child of the anchor. Any failure
in the job gives the render slot back (the person got nothing) and is reported on the board
as `view.failed`.
"""

import logging
import uuid
from functools import partial
from typing import Any

from sqlalchemy.orm import Session

from app import events, jobs
from app.analysis import limits
from app.analysis.extract import Bounds, release_slot, reserve_slot
from app.api.schemas import item_to_dict
from app.config import get_settings
from app.db.models import BoardItem
from app.db.session import after_commit, on_rollback
from app.errors import AppError
from app.extraction.service import _image_for, _require_item
from app.ingest.common import ItemMeta, create_item, default_size
from app.providers import get_image_provider
from app.providers.reliability import ModelError
from app.put.service import _name, _open, _stamped, result_check
from app.storage import files

log = logging.getLogger(__name__)

JOB = "render_view"

VIEW_PROMPT = (
    "Show this same design, {view}. It must read as the very same one: the same shape, "
    "proportions, colours, materials and details, in the same design language. Photo-real."
)


def view_prompt(view: str, words: str | None) -> str:
    prompt = VIEW_PROMPT.format(view=view.strip())
    extra = (words or "").strip().rstrip(".")
    return f"{prompt} {extra}." if extra else prompt


def _anchor(session: Session, anchor_id: str) -> BoardItem:
    """The anchor, live, a shown image: 404 ITEM_NOT_FOUND / 422 VIEW_NOT_IMAGE."""
    anchor = _require_item(session, anchor_id)
    if anchor.kind != "image" or not anchor.storage_path or anchor.staged:
        raise AppError(422, "VIEW_NOT_IMAGE", "Only a picture can be seen from another view")
    return anchor


def _enqueue(board_id: str, name: str, **kwargs: Any) -> None:
    """Queue the job; if that fails nothing will ever release its slot, so release it here."""
    try:
        jobs.enqueue(name, **kwargs)
    except Exception:
        release_slot(board_id, kwargs["job_id"])
        raise


def request_render_view(
    session: Session, anchor_id: str, view: str, words: str | None
) -> dict[str, Any]:
    """Check, count one render, and queue the job; where the result will land. A refused
    request costs no render."""
    anchor = _anchor(session, anchor_id)
    limits.check_and_count(anchor.board_id, "render")
    job_id = "view_" + uuid.uuid4().hex
    try:
        w, h = default_size(anchor.width or 1, anchor.height or 1)
        near = Bounds(anchor.x, anchor.y, anchor.w, anchor.h)
        x, y = reserve_slot(session, anchor.board_id, near, (w, h), job_id)
    except Exception:
        limits.refund(anchor.board_id, "render")
        raise
    board_id = anchor.board_id
    on_rollback(session, partial(release_slot, board_id, job_id))  # the request itself failed
    after_commit(
        session,
        partial(
            _enqueue, board_id, JOB, job_id=job_id, anchor_id=anchor.id, view=view, words=words,
            x=x, y=y,
        ),
    )  # fmt: skip
    return {"job_id": job_id, "x": x, "y": y, "w": w, "h": h}


def _ingest(
    session: Session, anchor: BoardItem, data: bytes, view: str, model: str, prompt: str,
    job_id: str, x: float, y: float,
) -> BoardItem:  # fmt: skip
    """Store the result like an upload, shown at once where the request said it would land."""
    img = _open(data)
    data = _stamped(img, model, job_id, "muse:view")
    sha = files.sha256_hex(data)
    storage = files.save_original(data, sha, "png")
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    meta = ItemMeta(origin="generated", filename=f"{_name(anchor)}, {view}.png", x=x, y=y)
    return create_item(
        session, anchor.board_id, meta,
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=img.size[0], height=img.size[1], w=w, h=h, rights_status="generated",
        parent_item_id=anchor.id, staged=False,
        generation_json={"model": model, "prompt": prompt, "view": view, "view_job": job_id},
    )  # fmt: skip


def _render(
    session: Session, job_id: str, anchor_id: str, view: str, words: str | None,
    x: float, y: float,
) -> BoardItem:  # fmt: skip
    anchor = _anchor(session, anchor_id)
    data, _sha = _image_for(session, anchor)
    prompt = view_prompt(view, words)
    provider = get_image_provider(get_settings())
    edited = provider.edit(data, prompt)
    return _ingest(session, anchor, edited, view.strip(), provider.model, prompt, job_id, x, y)


def _failed(session: Session, board_id: str | None, job_id: str, code: str, message: str) -> None:
    """Give the render back and say so on the board."""
    if board_id is None:
        return
    limits.refund(board_id, "render")
    data = {"job_id": job_id, "code": code, "message": message}
    after_commit(session, partial(events.publish, board_id, "view.failed", data))
    session.commit()


def _board_of(session: Session, anchor_id: str) -> str | None:
    """The anchor's board, even when it has been removed since (the slot was its board's)."""
    anchor = session.get(BoardItem, anchor_id)
    return anchor.board_id if anchor is not None else None


def render_view(
    session: Session, job_id: str, anchor_id: str, view: str, words: str | None,
    x: float, y: float,
) -> None:  # fmt: skip
    try:
        item = _render(session, job_id, anchor_id, view, words, x, y)
    except (ModelError, AppError) as exc:
        session.rollback()
        _failed(session, _board_of(session, anchor_id), job_id, exc.code, exc.message)
        return
    item.check_json = result_check(session, item, f"the same design seen from {view.strip()}")
    added = item_to_dict(item)
    done = {"job_id": job_id, "item_id": item.id}
    after_commit(session, partial(events.publish, item.board_id, "item.added", added))
    after_commit(session, partial(events.publish, item.board_id, "view.done", done))
    after_commit(session, partial(jobs.enqueue, "analyse_item", item_id=item.id))  # read it
    session.commit()


def render_view_job(
    job_id: str, anchor_id: str, view: str, words: str | None, x: float, y: float
) -> None:
    from app.api import deps

    with deps._factory()() as session:
        board_id: str | None = None
        try:
            board_id = _board_of(session, anchor_id)
            render_view(session, job_id, anchor_id, view, words, x, y)
        except Exception:
            session.rollback()
            log.exception("render view of %s (job %s) failed", anchor_id, job_id)
            _failed(session, board_id, job_id, "VIEW_ERROR", "Could not make this view")
        finally:
            release_slot(board_id, job_id)


jobs.register(JOB, render_view_job)
