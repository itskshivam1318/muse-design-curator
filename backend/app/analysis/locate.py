"""Lazy part regions: box and text parts are stored; a mask part runs SAM the first time it is asked for."""

import io

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.types import Region
from app.config import get_settings
from app.db.models import ItemAttribute, ItemPart
from app.errors import AppError
from app.extraction.service import _image_for, _mask_rel, _part_mask, _require_item
from app.measure.palette import mask_ratio
from app.providers import get_segmentation
from app.providers.reliability import ModelError

MAX_PROMPT_WORDS = 3
MIN_MASK_RATIO = 0.001


def _lens_part(session: Session, item_id: str, key: str) -> ItemPart | None:
    """A part a lens-extracted dimension names but no part row backs (rows written by the lens
    extraction path): created as a mask part, as migration 0008 did for older rows."""
    named = session.scalar(
        select(ItemAttribute.id).where(ItemAttribute.item_id == item_id, ItemAttribute.part == key)
    )
    if named is None:
        return None
    part = ItemPart(
        item_id=item_id, key=key, label=key.replace("_", " ").capitalize(), region_kind="mask",
        source="ai",
    )  # fmt: skip
    session.add(part)
    session.flush()
    return part


def _part(session: Session, item_id: str, key: str) -> ItemPart:
    part = session.scalar(select(ItemPart).where(ItemPart.item_id == item_id, ItemPart.key == key))
    if part is None:
        part = _lens_part(session, item_id, key)
    if part is None or part.removed:
        raise AppError(404, "PART_NOT_FOUND", "Part not found")
    return part


def _mask_url(rel: str) -> str:
    return f"/api/media/{rel}"  # rel is "masks/<file>"


def _mask_region(part: ItemPart) -> Region:
    assert part.mask_path is not None
    box = part.region_json if isinstance(part.region_json, list) else None
    return Region(kind="mask", box=box, mask_url=_mask_url(part.mask_path))


def locate(session: Session, item_id: str, part_key: str) -> Region:
    """The region of one part; a mask part is segmented on first use and cached."""
    item = _require_item(session, item_id)
    part = _part(session, item.id, part_key)
    if part.region_kind == "box":
        return Region(kind="box", box=part.region_json)
    if part.region_kind == "text_range":
        return Region(kind="text_range", range=part.region_json)
    if part.mask_path:
        return _mask_region(part)

    image, sha = _image_for(session, item)
    prompt = " ".join(part.label.split()[:MAX_PROMPT_WORDS])
    try:
        seg = get_segmentation(get_settings())
        with Image.open(io.BytesIO(image)) as im:
            width, height = im.size
        mask, bbox = _part_mask(session, seg, image, sha, prompt, (height, width))
    except ModelError as e:
        raise AppError(502, "REGION_FAILED", "Could not locate this part") from e
    if mask is None or bbox is None or mask_ratio(mask, np.ones_like(mask)) < MIN_MASK_RATIO:
        raise AppError(422, "REGION_EMPTY", "Nothing found for this part")
    part.mask_path = _mask_rel(sha, prompt)
    part.region_json = [round(c, 6) for c in bbox]
    session.commit()
    return _mask_region(part)
