"""Pull one part out of an item into an item of its own, placed beside its source."""

import io
import threading
import time
import uuid
from dataclasses import dataclass
from functools import partial

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy.orm import Session

from app import events, jobs
from app.analysis import limits
from app.analysis.locate import locate
from app.api.schemas import item_to_dict
from app.db.models import BoardItem
from app.db.repos import items as items_repo
from app.db.session import after_commit
from app.errors import AppError
from app.extraction.service import _image_for, _require_item
from app.ingest.common import ItemMeta, create_item, default_size
from app.notes.service import NOTE_H, NOTE_W
from app.plugins.registry import load_builtin_module
from app.storage import files

GAP = 40
MAX_STEPS = 200


@dataclass(frozen=True)
class Bounds:
    x: float
    y: float
    w: float
    h: float


def _hits(a: Bounds, b: Bounds) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


# Slots promised to queued jobs whose picture does not exist yet: board -> job -> (bounds, when).
RESERVATION_TTL_S = 600.0  # a job that never reports back must not hold its slot forever
_reserved: dict[str, dict[str, tuple[Bounds, float]]] = {}
_reserved_lock = threading.RLock()


def _reserved_on(board_id: str) -> list[Bounds]:
    with _reserved_lock:
        held = _reserved.get(board_id, {})
        now = time.monotonic()
        for job_id in [j for j, (_b, t) in held.items() if now - t > RESERVATION_TTL_S]:
            del held[job_id]
        return [b for b, _t in held.values()]


def release_slot(board_id: str | None, job_id: str) -> None:
    """Give a reserved slot back (the picture arrived, or the job failed). Safe to repeat."""
    if board_id is None:
        return
    with _reserved_lock:
        held = _reserved.get(board_id)
        if held is not None:
            held.pop(job_id, None)
            if not held:
                del _reserved[board_id]


def reserve_slot(
    session: Session, board_id: str, near: Bounds, size: tuple[float, float], job_id: str
) -> tuple[float, float]:
    """free_slot, then hold that spot for `job_id` until release_slot, so a second request
    made before the first picture exists lands elsewhere. Atomic across threads."""
    with _reserved_lock:
        x, y = free_slot(session, board_id, near, size)
        _reserved.setdefault(board_id, {})[job_id] = (Bounds(x, y, *size), time.monotonic())
    return x, y


def free_slot(
    session: Session, board_id: str, near: Bounds, size: tuple[float, float], gap: float = GAP
) -> tuple[float, float]:
    """The first spot right of `near`, else below, else left, that no shown item covers and
    no queued job has reserved.

    Each side is scanned in steps of `gap`, moving away from `near`; the result is deterministic.
    """
    w, h = size
    taken = [
        Bounds(i.x, i.y, i.w, i.h)
        for i in items_repo.list_active(session, board_id, include_staged=False)
    ] + _reserved_on(board_id)
    right = (near.x + near.w + gap, near.y)
    below = (near.x, near.y + near.h + gap)
    left = (near.x - gap - w, near.y)
    steps = {
        "right": lambda k: (right[0], right[1] + k * gap),
        "below": lambda k: (below[0] + k * gap, below[1]),
        "left": lambda k: (left[0], left[1] + k * gap),
    }
    for side in ("right", "below", "left"):
        for k in range(MAX_STEPS):
            x, y = steps[side](k)
            if not any(_hits(Bounds(x, y, w, h), t) for t in taken):
                return x, y
    return right  # a board this crowded: put it at the first choice


def _rights(source: BoardItem) -> str:
    return "user_supplied" if source.rights_status == "user_supplied" else "generated"


def _empty() -> AppError:
    return AppError(422, "REGION_EMPTY", "Nothing found for this part")


def _crop(source: BoardItem, image: bytes, box: list[float], mask_rel: str | None) -> bytes:
    """The box region of the image as PNG; with a mask the outside of the part is transparent."""
    with Image.open(io.BytesIO(image)) as im:
        rgb = im.convert("RGB")
    width, height = rgb.size
    x0, y0 = int(box[0] * width), int(box[1] * height)
    x1, y1 = int(np.ceil(box[2] * width)), int(np.ceil(box[3] * height))
    keep = None
    if mask_rel is not None:
        with Image.open(files.abs_path(mask_rel)) as m:
            alpha = m.convert("L").resize((width, height), Image.Resampling.NEAREST)
        keep = np.asarray(alpha) > 127
    try:
        out = load_builtin_module("cleanup", "cutout").cutout(rgb, keep, (x0, y0, x1, y1))
    except ValueError:
        raise _empty() from None
    info = PngInfo()
    info.add_text("muse:extracted_from", source.id)
    info.add_text("muse:nonce", uuid.uuid4().hex)  # an equal crop is still its own item
    buf = io.BytesIO()
    out.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _image_child(
    session: Session, source: BoardItem, part_key: str, filename: str, box: list[float],
    mask_rel: str | None,
) -> BoardItem:  # fmt: skip
    image, _sha = _image_for(session, source)
    data = _crop(source, image, box, mask_rel)
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        size = img.size
        sha = files.sha256_hex(data)
        storage = files.save_original(data, sha, "png")
        thumb = files.save_thumb(img, sha)
    w, h = default_size(*size)
    x, y = free_slot(
        session, source.board_id, Bounds(source.x, source.y, source.w, source.h), (w, h)
    )
    return create_item(
        session, source.board_id, ItemMeta(origin="generated", filename=filename, x=x, y=y),
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=size[0], height=size[1], w=w, h=h, rights_status=_rights(source),
        parent_item_id=source.id, extracted_part=part_key,
    )  # fmt: skip


def _note_child(session: Session, source: BoardItem, part_key: str, span: list[int]) -> BoardItem:
    text = (source.note_text or "")[span[0] : span[1]]
    if not text.strip():
        raise _empty()
    x, y = free_slot(
        session, source.board_id, Bounds(source.x, source.y, source.w, source.h), (NOTE_W, NOTE_H)
    )
    return create_item(
        session, source.board_id, ItemMeta(origin="generated", x=x, y=y),
        kind="note", note_text=text, w=NOTE_W, h=NOTE_H, rights_status=_rights(source),
        parent_item_id=source.id, extracted_part=part_key,
    )  # fmt: skip


def extract(session: Session, item_id: str, part_key: str) -> BoardItem:
    """Make the part its own item: a crop (cut out by its mask when it has one) or a note.

    Nothing is created when the region is empty. The new item is analysed like any other.
    """
    source = _require_item(session, item_id)
    limits.check_and_count(source.board_id, "analyse")
    try:
        child = _extract(session, source, item_id, part_key)
    except AppError:
        limits.refund(source.board_id, "analyse")  # nothing was made, so nothing is spent
        raise
    after_commit(
        session, partial(events.publish, child.board_id, "item.added", item_to_dict(child))
    )
    # a new item, pending like an upload: queued once, free (the extract took the slot)
    after_commit(session, partial(jobs.enqueue, "analyse_item", item_id=child.id))
    return child


def _extract(session: Session, source: BoardItem, item_id: str, part_key: str) -> BoardItem:
    region = locate(session, item_id, part_key)
    if region.kind == "text_range":
        if source.kind != "note" or region.range is None:
            raise _empty()
        child = _note_child(session, source, part_key, region.range)
    else:
        if region.box is None:
            raise _empty()
        mask_rel = region.mask_url.removeprefix("/api/media/") if region.mask_url else None
        child = _image_child(session, source, part_key, f"{part_key}.png", region.box, mask_rel)
    return child


__all__ = ["Bounds", "extract", "free_slot", "release_slot", "reserve_slot"]
