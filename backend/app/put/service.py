"""Put into: a new picture of the target with the source blended into chosen spots.

The request checks both pictures and the spots, takes a render slot and queues the job; it
answers with where the result will land. The job pastes the source's subject into each spot,
asks the image model to blend it in, and composites the edit back inside the spots only. Any
failure in the job gives the render slot back (the person got nothing) and is reported on the
board as `put.failed`.
"""

import io
import logging
import uuid
from functools import partial
from pathlib import PurePath
from typing import Any

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events, jobs
from app.analysis import limits
from app.analysis.extract import Bounds, free_slot
from app.analysis.locate import locate
from app.analysis.types import Region
from app.api.schemas import item_to_dict
from app.config import get_settings
from app.db.models import BoardItem, ItemPart
from app.db.session import after_commit
from app.errors import AppError
from app.extraction.service import _image_for, _require_item
from app.ingest.common import ItemMeta, create_item, default_size
from app.providers import get_image_provider
from app.providers.reliability import ModelError
from app.put.render import (
    Box,
    cut_out,
    has_alpha,
    paste_into,
    point_box,
    put_prompt,
    region_box,
    spots_mask,
)
from app.render.composite import composite_in_region
from app.storage import files

log = logging.getLogger(__name__)

JOB = "put_into"
POINT_NAME = "the marked spot"
SUBJECT_COVER = 0.6  # a part whose box covers this much of the source is its subject
FALLBACK_NAME = "the reference"


def _not_image() -> AppError:
    return AppError(422, "PUT_NOT_IMAGE", "Only a picture can be put into another picture")


def _pictures(session: Session, target_id: str, source_id: str) -> tuple[BoardItem, BoardItem]:
    """Both items, live, shown images and distinct: 404 ITEM_NOT_FOUND / 422 PUT_NOT_IMAGE."""
    target = _require_item(session, target_id)
    source = _require_item(session, source_id)
    if target.id == source.id or target.board_id != source.board_id:
        raise _not_image()
    for item in (target, source):
        if item.kind != "image" or not item.storage_path or item.staged:
            raise _not_image()
    return target, source


def _live_part(session: Session, item_id: str, key: str) -> ItemPart:
    part = session.scalar(
        select(ItemPart).where(
            ItemPart.item_id == item_id, ItemPart.key == key, ItemPart.removed.is_(False)
        )
    )
    if part is None:
        raise AppError(422, "PART_NOT_FOUND", "That spot is not a part of this picture")
    return part


def _check_spots(session: Session, target: BoardItem, spots: list[dict[str, Any]]) -> None:
    for spot in spots:
        if "part" in spot:
            _live_part(session, target.id, spot["part"])


def request_put_into(
    session: Session, target_id: str, source_id: str, spots: list[dict[str, Any]],
    words: str | None,
) -> dict[str, Any]:  # fmt: skip
    """Check, count one render, and queue the job; where the result will land. A refused
    request costs no render."""
    target, source = _pictures(session, target_id, source_id)
    _check_spots(session, target, spots)
    limits.check_and_count(target.board_id, "render")
    try:
        w, h = default_size(target.width or 1, target.height or 1)
        near = Bounds(target.x, target.y, target.w, target.h)
        x, y = free_slot(session, target.board_id, near, (w, h))
    except Exception:
        limits.refund(target.board_id, "render")
        raise
    job_id = "put_" + uuid.uuid4().hex
    after_commit(
        session,
        partial(
            jobs.enqueue, JOB, job_id=job_id, target_id=target.id, source_id=source.id,
            spots=spots, words=words, x=x, y=y,
        ),
    )  # fmt: skip
    return {"job_id": job_id, "x": x, "y": y, "w": w, "h": h}


def _name(item: BoardItem) -> str:
    """The item's title as the board shows it: page title, else file name without extension."""
    if item.page_title and item.page_title.strip():
        return item.page_title.strip()
    if item.original_filename and PurePath(item.original_filename).stem.strip():
        return PurePath(item.original_filename).stem.strip()
    return FALLBACK_NAME


def _mask_of(session: Session, item: BoardItem, key: str, size: tuple[int, int]) -> np.ndarray:
    """The part's region as a bool mask the size of the item's picture (located if need be)."""
    region = locate(session, item.id, key)
    w, h = size
    if region.kind == "box" and region.box is not None:
        x0, y0, x1, y1 = region_box(size, region.box)
        mask = np.zeros((h, w), dtype=bool)
        mask[max(y0, 0) : min(y1, h), max(x0, 0) : min(x1, w)] = True
        return mask
    if region.kind != "mask":
        raise AppError(422, "REGION_EMPTY", "Nothing found for this part")
    part = _live_part(session, item.id, key)
    path = files.abs_path(part.mask_path) if part.mask_path else None
    if path is None or not path.is_file():
        raise AppError(502, "REGION_FAILED", "Could not locate this part")
    with Image.open(path) as m:
        mask = np.asarray(m.convert("L")) > 127
    if mask.shape != (h, w):
        fitted = Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)
        mask = np.asarray(fitted) > 127
    if not mask.any():
        raise AppError(422, "REGION_EMPTY", "Nothing found for this part")
    return mask


def _area(part: ItemPart) -> float:
    r = part.region_json
    if not isinstance(r, list) or len(r) != 4:
        return 0.0
    return max(0.0, float(r[2]) - float(r[0])) * max(0.0, float(r[3]) - float(r[1]))


def _subject_part(session: Session, source: BoardItem) -> ItemPart | None:
    """The one image part, else the part covering at least SUBJECT_COVER of the picture."""
    parts = list(
        session.scalars(
            select(ItemPart).where(
                ItemPart.item_id == source.id,
                ItemPart.removed.is_(False),
                ItemPart.region_kind.in_(("mask", "box")),
            )
        )
    )
    if len(parts) == 1:
        return parts[0]
    big = [p for p in parts if _area(p) >= SUBJECT_COVER]
    return max(big, key=_area, default=None)


def subject_of(session: Session, source: BoardItem) -> tuple[Image.Image, str]:
    """What gets pasted, and its name: the picture as is when it has transparency; else its
    main part cut out by its mask; else the whole picture."""
    data, _sha = _image_for(session, source)
    img = _open(data)
    name = _name(source)
    if has_alpha(img):
        return img.convert("RGBA"), name
    part = _subject_part(session, source)
    if part is not None:
        try:
            mask = _mask_of(session, source, part.key, img.size)
        except AppError:
            log.info("no cut-out for part %s of %s: using the whole picture", part.key, source.id)
        else:
            return cut_out(img, mask), name
    return img.convert("RGB"), name


def _spots(
    session: Session, target: BoardItem, size: tuple[int, int], spots: list[dict[str, Any]]
) -> tuple[list[tuple[Box, np.ndarray | None]], list[str]]:
    """Each spot's pixel box and mask (None for a point or a box part), and its name."""
    out: list[tuple[Box, np.ndarray | None]] = []
    names: list[str] = []
    for spot in spots:
        if "part" in spot:
            part = _live_part(session, target.id, spot["part"])
            mask = _mask_of(session, target, part.key, size)
            ys, xs = np.nonzero(mask)
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            out.append((box, None if part.region_kind == "box" else mask))
            names.append(part.label)
        else:
            point = spot["point"]
            out.append((point_box(size, float(point["fx"]), float(point["fy"])), None))
            names.append(POINT_NAME)
    return out, names


def _open(data: bytes) -> Image.Image:
    """A stored picture (already checked when it came in), decoded."""
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _png(img: Image.Image, info: PngInfo | None = None) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _stamped(img: Image.Image, model: str, job_id: str) -> bytes:
    """PNG bytes carrying their provenance and the job, so the same result twice (a
    deterministic model) is still a distinct file for the board's sha index."""
    info = PngInfo()
    info.add_text("Software", model)
    info.add_text("muse:put", job_id)
    return _png(img, info)


def _bbox(mask: np.ndarray) -> list[float]:
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    return [xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h]


def _ingest(
    session: Session, target: BoardItem, source: BoardItem, data: bytes, subject: str,
    model: str, prompt: str, job_id: str, x: float, y: float,
) -> BoardItem:  # fmt: skip
    """Store the result like an upload, shown at once where the request said it would land."""
    img = _open(data)
    data = _stamped(img, model, job_id)
    sha = files.sha256_hex(data)
    storage = files.save_original(data, sha, "png")
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    meta = ItemMeta(origin="generated", filename=f"{_name(target)} with {subject}.png", x=x, y=y)
    return create_item(
        session, target.board_id, meta,
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=img.size[0], height=img.size[1], w=w, h=h, rights_status="generated",
        parent_item_id=target.id, put_source_item_id=source.id, staged=False,
        generation_json={"model": model, "prompt": prompt, "put_job": job_id},
    )  # fmt: skip


def _render(
    session: Session, job_id: str, target_id: str, source_id: str, spots: list[dict[str, Any]],
    words: str | None, x: float, y: float,
) -> BoardItem:  # fmt: skip
    target, source = _pictures(session, target_id, source_id)
    data, _sha = _image_for(session, target)
    size = _open(data).size
    boxes, names = _spots(session, target, size, spots)
    subject, subject_name = subject_of(session, source)
    with Image.open(io.BytesIO(data)) as im:
        pasted = paste_into(im, subject, [b for b, _m in boxes])
    prompt = put_prompt(subject_name, names, words)
    provider = get_image_provider(get_settings())
    edited = provider.edit(_png(pasted), prompt)
    union = spots_mask(size, boxes)
    if not union.any():
        raise AppError(422, "REGION_EMPTY", "Nothing found for this spot")
    region = Region(kind="mask", box=_bbox(union))
    result = composite_in_region(data, edited, region, union)
    return _ingest(
        session, target, source, result, subject_name, provider.model, prompt, job_id, x, y
    )


def _failed(session: Session, board_id: str | None, job_id: str, code: str, message: str) -> None:
    """Give the render back and say so on the board."""
    if board_id is None:
        return
    limits.refund(board_id, "render")
    data = {"job_id": job_id, "code": code, "message": message}
    after_commit(session, partial(events.publish, board_id, "put.failed", data))
    session.commit()


def _board_of(session: Session, target_id: str) -> str | None:
    """The target's board, even when it has been removed since (the slot was its board's)."""
    target = session.get(BoardItem, target_id)
    return target.board_id if target is not None else None


def put_into(
    session: Session, job_id: str, target_id: str, source_id: str, spots: list[dict[str, Any]],
    words: str | None, x: float, y: float,
) -> None:  # fmt: skip
    try:
        item = _render(session, job_id, target_id, source_id, spots, words, x, y)
    except (ModelError, AppError) as exc:
        session.rollback()
        _failed(session, _board_of(session, target_id), job_id, exc.code, exc.message)
        return
    added = item_to_dict(item)
    done = {"job_id": job_id, "item_id": item.id}
    after_commit(session, partial(events.publish, item.board_id, "item.added", added))
    after_commit(session, partial(events.publish, item.board_id, "put.done", done))
    session.commit()


def put_into_job(
    job_id: str, target_id: str, source_id: str, spots: list[dict[str, Any]],
    words: str | None, x: float, y: float,
) -> None:  # fmt: skip
    from app.api import deps

    with deps._factory()() as session:
        try:
            put_into(session, job_id, target_id, source_id, spots, words, x, y)
        except Exception:
            session.rollback()
            log.exception("put into %s (job %s) failed", target_id, job_id)
            board_id = _board_of(session, target_id)
            _failed(session, board_id, job_id, "PUT_ERROR", "Could not make this picture")


jobs.register(JOB, put_into_job)
