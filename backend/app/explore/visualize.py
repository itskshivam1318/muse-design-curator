"""Visualize one option: edit the source image, add the result to the board, parse and check it.

The request marks the option `visualizing` and queues the job. The job edits the image and
stores it as a generated item beside the option's note; a failure there leaves no item and puts
the option back. After that the item stays: a parse or check failure is stored on it.
"""

import io
import logging
import uuid
from functools import partial
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import events, jobs
from app.api.schemas import item_to_dict
from app.config import get_settings
from app.db.models import BoardItem, Exploration, ExploreOption
from app.db.repos import explore as explore_repo
from app.db.session import after_commit
from app.errors import AppError
from app.explore.check import check_generated
from app.explore.service import publish_later, require_enabled, resting_status
from app.explore.vocab import add_vocabulary
from app.extraction.service import _image_for, _require_item, parse_item
from app.ingest.common import ItemMeta, create_item, default_size
from app.ingest.images import decode_image
from app.providers import get_image_provider
from app.providers.reliability import ModelError
from app.storage import files

log = logging.getLogger(__name__)

JOB = "visualize_option"
NOTE_GAP = 40  # source edge to the option's note when the note has no saved position
NOTE_WIDTH = 260  # the generated item sits past the note


def _exploration(session: Session, o: ExploreOption) -> Exploration:
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    return e


def request_visualize(session: Session, option_id: str) -> None:
    """Mark the option visualizing and queue the job; 409 while it is already visualizing."""
    require_enabled()
    o = explore_repo.get_option(session, option_id)
    if o is None:
        raise AppError(404, "OPTION_NOT_FOUND", "Option not found")
    e = _exploration(session, o)
    _require_item(session, e.item_id)
    claimed = session.execute(
        update(ExploreOption)
        .where(ExploreOption.id == option_id, ExploreOption.status != "visualizing")
        .values(status="visualizing", last_error=None)
    )  # fmt: skip
    if not claimed.rowcount:  # type: ignore[attr-defined]
        raise AppError(409, "VISUALIZE_IN_PROGRESS", "This option is already being visualized")
    session.refresh(o)
    publish_later(session, e)
    after_commit(session, partial(jobs.enqueue, JOB, option_id=option_id))


def _stamped(img: Image.Image, model: str, option_id: str) -> bytes:
    """PNG bytes carrying their provenance and a nonce, so an identical edit (a deterministic
    model, a retry) is still a distinct file and does not collide with the board's sha index."""
    info = PngInfo()
    info.add_text("Software", model)
    info.add_text("muse:option", option_id)
    info.add_text("muse:nonce", uuid.uuid4().hex)
    if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _ingest(
    session: Session, source: BoardItem, o: ExploreOption, data: bytes, model: str
) -> BoardItem:
    """Store the edited image like an upload, never deduped: each visualize is a new item."""
    img = decode_image(data)
    data = _stamped(img, model, o.id)
    sha = files.sha256_hex(data)
    storage = files.save_original(data, sha, "png")
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    x = (o.x if o.x is not None else source.x + source.w + NOTE_GAP) + NOTE_WIDTH
    y = o.y if o.y is not None else source.y
    return create_item(
        session, source.board_id, ItemMeta(origin="generated", x=x, y=y),
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=img.size[0], height=img.size[1], w=w, h=h, rights_status="generated",
        parent_item_id=source.id, explore_option_id=o.id,
        generation_json={"model": model, "prompt": o.edit_prompt, "option_id": o.id},
    )  # fmt: skip


def _settle(session: Session, option_id: str, error: str | None) -> None:
    """End the visualizing state: visualized when the option has an image, else open."""
    o = explore_repo.get_option(session, option_id)
    if o is None:
        return
    if o.status == "visualizing":
        o.status = resting_status(session, o.id)
    o.last_error = error
    session.flush()
    publish_later(session, _exploration(session, o))


def _check(session: Session, source_id: str, item_id: str, o: ExploreOption) -> dict[str, Any]:
    """Parse the new item, then check it; a failure is stored as {"error": code}."""
    try:
        parse_item(session, item_id)  # commits; a model failure marks the item failed
    except AppError as exc:
        return {"error": exc.code}
    session.expire_all()
    item = _require_item(session, item_id)
    if item.parse_status == "failed":
        return {"error": item.parse_error_code or "PARSE_ERROR"}
    try:
        return check_generated(session, source_id, item_id, o)
    except (ModelError, AppError) as exc:
        return {"error": exc.code}


def visualize(session: Session, option_id: str) -> None:
    o = explore_repo.get_option(session, option_id)
    if o is None:
        return
    e = _exploration(session, o)
    provider = get_image_provider(get_settings())
    try:
        source = _require_item(session, e.item_id)
        image, _sha = _image_for(session, source)
        edited = provider.edit(image, o.edit_prompt)
        item = _ingest(session, source, o, edited, provider.model)
    except (ModelError, AppError) as exc:
        session.rollback()
        _settle(session, option_id, exc.code)
        session.commit()
        return
    added = item_to_dict(item)
    after_commit(session, partial(events.publish, item.board_id, "item.added", added))
    session.commit()

    add_vocabulary(session, e.board_id, e.key, o.value_json)
    session.commit()

    check = _check(session, source.id, item.id, o)
    item = _require_item(session, item.id)
    item.check_json = check
    session.flush()
    data = item_to_dict(item)
    after_commit(session, partial(events.publish, item.board_id, "item.updated", data))
    _settle(session, option_id, None)
    session.commit()


def visualize_job(option_id: str) -> None:
    from app.api import deps

    with deps._factory()() as session:
        try:
            visualize(session, option_id)
        except Exception:
            session.rollback()
            log.exception("visualizing option %s failed", option_id)
            _settle(session, option_id, "VISUALIZE_ERROR")
            session.commit()


jobs.register(JOB, visualize_job)
