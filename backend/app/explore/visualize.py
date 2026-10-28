"""Visualize one option: edit the source image, add the result to the board, parse and check it.

The request marks the option `visualizing` and queues the job. The job edits the image and
stores it as a generated item beside the option's note; a failure there leaves no item and puts
the option back. After that the item stays: a parse or check failure is stored on it.
"""

import io
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import events, jobs
from app.api.schemas import item_to_dict
from app.config import get_settings
from app.db.ids import now_iso
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
NOTE_OFFSET = 60  # source edge to the note's first fan column (the browser's OFFSET_X)
NOTE_WIDTH = 220  # the browser's NOTE_W
IMAGE_GAP = 40  # note edge to the generated item
STACK_GAP = 24  # between images generated from the same option
UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
CLAIM_TTL_S = 300  # a visualize claim older than this is from a job that died


def _exploration(session: Session, o: ExploreOption) -> Exploration:
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    return e


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")  # the same shape as now_iso: comparable text


def request_visualize(
    session: Session, option_id: str, *, at: tuple[float, float] | None = None
) -> None:
    """Mark the option visualizing and queue the job. 409 while it is already visualizing,
    unless that claim is older than CLAIM_TTL_S (its job died with the process).

    `at` is where the browser drew the note (a never-dragged note's spot is computed there);
    it is saved on the option so the image lands beside it."""
    require_enabled()
    o = explore_repo.get_option(session, option_id)
    if o is None:
        raise AppError(404, "OPTION_NOT_FOUND", "Option not found")
    e = _exploration(session, o)
    _require_item(session, e.item_id)
    stale = _iso(datetime.now(UTC) - timedelta(seconds=CLAIM_TTL_S))
    claimed = session.execute(
        update(ExploreOption)
        .where(
            ExploreOption.id == option_id,
            or_(
                ExploreOption.status != "visualizing",
                ExploreOption.visualize_claimed_at.is_(None),
                ExploreOption.visualize_claimed_at < stale,
            ),
        )
        .values(
            status="visualizing", last_error=None, visualize_claimed_at=now_iso(),
            **({"x": at[0], "y": at[1]} if at else {}),
        )
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


def _title(name: str) -> str:
    """A readable file name for the generated item: the option's name, made safe."""
    safe = UNSAFE.sub("-", name).strip(" .")[:120]
    return f"{safe or 'generated'}.png"


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
    # right of the option's note; each repeat below the one before, so they never stack
    note_x = o.x if o.x is not None else source.x + source.w + NOTE_OFFSET
    note_y = o.y if o.y is not None else source.y
    done = explore_repo.generated_count(session, o.id)
    x, y = note_x + NOTE_WIDTH + IMAGE_GAP, note_y + done * (h + STACK_GAP)
    meta = ItemMeta(origin="generated", filename=_title(o.name), x=x, y=y)
    return create_item(
        session, source.board_id, meta,
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
    o.visualize_claimed_at = None
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
    except Exception:
        log.exception("checking generated item %s failed", item_id)
        return {"error": "CHECK_ERROR"}


def visualize(session: Session, option_id: str) -> None:
    o = explore_repo.get_option(session, option_id)
    if o is None:
        return
    e = _exploration(session, o)
    try:
        provider = get_image_provider(get_settings())
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

    try:  # a lens that could not grow never costs the user the image or its check
        add_vocabulary(session, e.board_id, e.key, o.value_json)
        session.commit()
    except Exception:
        session.rollback()
        log.exception("adding %r to %s on board %s failed", o.value_json, e.key, e.board_id)

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


def recover_stuck(session: Session) -> int:
    """Startup: no job survives a restart, so `visualizing` options go back to rest, every
    claim is freed, and a generated item whose check never finished is marked INTERRUPTED."""
    stuck = list(
        session.scalars(select(ExploreOption).where(ExploreOption.status == "visualizing"))
    )
    for o in stuck:
        o.status = resting_status(session, o.id)
    claimed = select(ExploreOption).where(ExploreOption.visualize_claimed_at.is_not(None))
    for o in session.scalars(claimed):
        o.visualize_claimed_at = None  # also options dismissed mid-job
    for item in session.scalars(select(BoardItem).where(BoardItem.origin == "generated")):
        if item.check_json is None:
            item.check_json = {"error": "INTERRUPTED"}
    session.flush()
    return len(stuck)


jobs.register(JOB, visualize_job)
