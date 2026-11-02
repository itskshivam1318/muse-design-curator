"""Visualize one option: render a take of the source item, add it to the board, parse and check it.

The request picks the renderer, marks the option `visualizing` and queues the job. The job renders
the take and stores it staged (hidden from the canvas until kept); a failure there leaves no item
and puts the option back. After that the item stays: a parse or check failure is stored on it.

Muse Image edits the whole image; for a physical dimension only the pixels inside the part's
region (mask, or box on a UI screen) are composited back. Spark rewrite changes only the
passage of a note and stores the result as a new note beside it.
"""

import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app import events, jobs
from app.analysis import limits
from app.analysis.extract import Bounds, free_slot
from app.analysis.locate import locate
from app.analysis.service import analyse
from app.analysis.types import Region
from app.api.schemas import item_to_dict
from app.config import get_settings
from app.db.ids import now_iso
from app.db.models import BoardItem, Exploration, ExploreOption, ItemAttribute, ItemPart
from app.db.repos import explore as explore_repo
from app.db.session import after_commit
from app.errors import AppError
from app.explore.check import check_generated
from app.explore.service import (
    _part_label,
    dimensions,
    publish_later,
    require_enabled,
    resting_status,
)
from app.explore.vocab import add_vocabulary
from app.extraction.service import _image_for, _require_item
from app.ingest.common import ItemMeta, create_item, default_size
from app.ingest.images import decode_image
from app.notes.service import NOTE_H, NOTE_W
from app.plugins.runners import PART_PROMPT
from app.providers import get_image_provider, get_reasoning
from app.providers.reliability import ModelError
from app.render.composite import composite_in_region
from app.render.registry import SPARK_REWRITE, RendererInfo, is_physical, pick_renderer
from app.render.rewrite import rewrite_passage, span
from app.storage import files

log = logging.getLogger(__name__)

JOB = "visualize_option"
IMAGE_GAP = 40  # note edge to the generated item (used by note visualize)
STACK_GAP = 24  # between images generated from the same option
UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
CLAIM_TTL_S = 300  # a visualize claim older than this is from a job that died


def _exploration(session: Session, o: ExploreOption) -> Exploration:
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    return e


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")  # the same shape as now_iso: comparable text


def _dimension(session: Session, item_id: str, key: str) -> ItemAttribute | None:
    """The explored dimension's row on the source item (None: treated as abstract)."""
    return next((r for r in dimensions(session, item_id) if r.key == key), None)


def request_visualize(
    session: Session, option_id: str, *, at: tuple[float, float] | None = None,
    renderer_id: str | None = None,
) -> None:  # fmt: skip
    """Pick the renderer (`renderer_id`, else the first for the item), mark the option
    visualizing and queue the job. 409 while it is already visualizing, unless that claim is
    older than CLAIM_TTL_S (its job died with the process). A refused request (daily limit,
    no such renderer, 409) leaves the option as it was and costs no render.

    `at` is where the browser drew the note (a never-dragged note's spot is computed there);
    it is saved on the option so the image lands beside it."""
    require_enabled()
    o = explore_repo.get_option(session, option_id)
    if o is None:
        raise AppError(404, "OPTION_NOT_FOUND", "Option not found")
    e = _exploration(session, o)
    item = _require_item(session, e.item_id)
    limits.check_and_count(item.board_id, "render")
    try:
        info = pick_renderer(session, item, _dimension(session, item.id, e.key), renderer_id)
    except AppError:
        limits.refund(item.board_id, "render")
        raise
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
        limits.refund(item.board_id, "render")
        raise AppError(409, "VISUALIZE_IN_PROGRESS", "This option is already being visualized")
    session.refresh(o)
    publish_later(session, e)
    after_commit(session, partial(jobs.enqueue, JOB, option_id=option_id, renderer_id=info.id))


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
    session: Session, source: BoardItem, o: ExploreOption, data: bytes, model: str,
    renderer: str, prompt: str,
) -> BoardItem:  # fmt: skip
    """Store the edited image like an upload, never deduped: each visualize is a new item."""
    img = decode_image(data)
    data = _stamped(img, model, o.id)
    sha = files.sha256_hex(data)
    storage = files.save_original(data, sha, "png")
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    # a take is staged, not drawn: it sits at the source until the user keeps it somewhere
    x, y = source.x, source.y
    meta = ItemMeta(origin="generated", filename=_title(o.name), x=x, y=y)
    return create_item(
        session, source.board_id, meta,
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=img.size[0], height=img.size[1], w=w, h=h, rights_status="generated",
        parent_item_id=source.id, explore_option_id=o.id, staged=True,
        generation_json={"model": model, "prompt": prompt, "option_id": o.id,
                         "renderer": renderer},
    )  # fmt: skip


@dataclass
class _Area:
    region: Region
    mask: np.ndarray | None


def _region_empty() -> AppError:
    return AppError(422, "REGION_EMPTY", "Nothing found for this part")


def _region_of(session: Session, source: BoardItem, row: ItemAttribute) -> Region:
    """The physical dimension's part region (located now if need be): 404/422/502 AppError."""
    if not row.part:
        raise _region_empty()
    return locate(session, source.id, row.part)  # commits a newly located mask


def _area(session: Session, source: BoardItem, row: ItemAttribute | None) -> _Area | None:
    """Where a physical dimension's edit is composited back: its part's mask or box. None for
    an abstract dimension: the whole image changes. A region that cannot be used is refused
    (never widened to the whole image)."""
    if row is None or not is_physical(row):
        return None
    region = _region_of(session, source, row)
    if region.kind == "box":
        if region.box is None:
            raise _region_empty()
        return _Area(region, None)
    if region.kind != "mask":
        raise _region_empty()  # a text range on an image: nothing to composite inside
    part = session.scalar(
        select(ItemPart).where(ItemPart.item_id == source.id, ItemPart.key == row.part)
    )
    path = files.abs_path(part.mask_path) if part is not None and part.mask_path else None
    if path is None or not path.is_file():
        raise AppError(502, "REGION_FAILED", "Could not locate this part")
    with Image.open(path) as m:
        mask = np.asarray(m.convert("L")) > 127
    if not mask.any():
        raise _region_empty()
    return _Area(region, mask)


def _passage(
    session: Session, source: BoardItem, row: ItemAttribute | None
) -> tuple[int, int] | None:
    """The physical dimension's text range, refused when it has none; None for an abstract
    dimension (the whole text is rewritten)."""
    if row is None or not is_physical(row):
        return None
    region = _region_of(session, source, row)
    if region.range is None:
        raise _region_empty()
    start, end = span(source.note_text or "", (region.range[0], region.range[1]))
    if start >= end:
        raise _region_empty()
    return start, end


def _render_image(
    session: Session, source: BoardItem, o: ExploreOption, row: ItemAttribute | None,
    info: RendererInfo, area: _Area | None,
) -> BoardItem:  # fmt: skip
    """Edit the whole image; composite it back inside the part's region when there is one."""
    provider = get_image_provider(get_settings())
    image, _sha = _image_for(session, source)
    prompt = o.edit_prompt
    if not info.builtin and area is not None and row is not None:  # a plugin's part prompt
        prompt = PART_PROMPT.format(part=_part_label(session, row), prompt=prompt.rstrip(" ."))
    edited = provider.edit(image, prompt)
    if area is not None:
        edited = composite_in_region(image, edited, area.region, area.mask)
    return _ingest(session, source, o, edited, provider.model, info.id, prompt)


def _rewrite(
    session: Session, source: BoardItem, o: ExploreOption, rng: tuple[int, int] | None
) -> BoardItem:
    """Rewrite the passage (the whole text when `rng` is None) into a new staged note beside
    the source; `changed_range` is where the new passage sits in it."""
    text = source.note_text or ""
    start, end = span(text, rng)
    new_text = rewrite_passage(text, rng, o.edit_prompt)
    new_len = len(new_text) - (len(text) - (end - start))
    near = Bounds(source.x, source.y, source.w, source.h)
    x, y = free_slot(session, source.board_id, near, (NOTE_W, NOTE_H))
    model = get_reasoning(get_settings()).model
    return create_item(
        session, source.board_id, ItemMeta(origin="generated", x=x, y=y),
        kind="note", note_text=new_text, w=NOTE_W, h=NOTE_H, rights_status="generated",
        parent_item_id=source.id, explore_option_id=o.id, staged=True,
        generation_json={"model": model, "prompt": o.edit_prompt, "option_id": o.id,
                         "renderer": SPARK_REWRITE, "changed_range": [start, start + new_len]},
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
        analyse(session, item_id)  # commits; a model failure marks the item failed
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


def visualize(session: Session, option_id: str, renderer_id: str | None = None) -> None:
    o = explore_repo.get_option(session, option_id)
    if o is None:
        return
    e = _exploration(session, o)
    try:
        try:  # nothing has rendered yet: a refusal here gives the render slot back
            source = _require_item(session, e.item_id)
            row = _dimension(session, source.id, e.key)
            info = pick_renderer(session, source, row, renderer_id)
            if info.id == SPARK_REWRITE:
                rng = _passage(session, source, row)
            else:
                area = _area(session, source, row)
        except (ModelError, AppError):
            limits.refund(e.board_id, "render")
            raise
        if info.id == SPARK_REWRITE:
            item = _rewrite(session, source, o, rng)
        else:
            item = _render_image(session, source, o, row, info, area)
    except (ModelError, AppError) as exc:
        session.rollback()
        _settle(session, option_id, exc.code)
        session.commit()
        return
    added = item_to_dict(item)
    after_commit(session, partial(events.publish, item.board_id, "item.added", added))
    session.commit()

    try:  # a lens that could not grow never costs the user the image or its check
        add_vocabulary(session, e.board_id, e.key, o.value_json, item_id=e.item_id)
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


def visualize_job(option_id: str, renderer_id: str | None = None) -> None:
    from app.api import deps

    with deps._factory()() as session:
        try:
            visualize(session, option_id, renderer_id)
        except Exception:
            session.rollback()
            log.exception("visualizing option %s failed", option_id)
            _settle(session, option_id, "VISUALIZE_ERROR")
            session.commit()


def recover_stuck(session: Session) -> int:
    """Startup: no job survives a restart, so `visualizing` options go back to rest, every
    claim is freed, and a generated item whose check never finished is marked INTERRUPTED
    (plugin outputs are never checked, so they are left alone)."""
    stuck = list(
        session.scalars(select(ExploreOption).where(ExploreOption.status == "visualizing"))
    )
    for o in stuck:
        o.status = resting_status(session, o.id)
    claimed = select(ExploreOption).where(ExploreOption.visualize_claimed_at.is_not(None))
    for o in session.scalars(claimed):
        o.visualize_claimed_at = None  # also options dismissed mid-job
    for item in session.scalars(select(BoardItem).where(BoardItem.origin == "generated")):
        if item.check_json is None and not (item.generation_json or {}).get("plugin"):
            item.check_json = {"error": "INTERRUPTED"}
    session.flush()
    return len(stuck)


jobs.register(JOB, visualize_job)
