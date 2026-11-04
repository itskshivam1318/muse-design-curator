"""Masks a python plugin asked for (`needs`): prepared on the host, handed over as PNG files."""

from __future__ import annotations

import io
from typing import TypedDict

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import limits
from app.analysis.locate import _box_mask, locate, locate_object, object_cached, part_cached
from app.db.models import BoardItem, ItemPart
from app.errors import AppError
from app.extraction.service import _fit, _image_for
from app.storage import files


class PreparedMasks(TypedDict):
    parts: list[tuple[str, str, np.ndarray]]
    object: np.ndarray | None


def _load(rel: str, height: int, width: int) -> np.ndarray:
    with Image.open(files.abs_path(rel)) as im:
        return _fit(np.asarray(im.convert("L")) > 127, height, width)


def _mask_from_url(url: str, height: int, width: int) -> np.ndarray:
    return _load(url.removeprefix("/api/media/"), height, width)


def png_bytes(mask: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(mask.astype(np.uint8) * 255).save(buf, "PNG")
    return buf.getvalue()


def prepare_masks(
    session: Session, board_id: str, item: BoardItem, needs: list[str]
) -> PreparedMasks:
    """The item's part masks and/or object mask (True = inside, image-sized). One "analyse" slot
    is taken only when a segmentation call is needed, and given back if preparing fails. A part
    or object nothing was found for is left out (None for the object)."""
    out: PreparedMasks = {"parts": [], "object": None}
    if item.kind not in ("image", "video") or not needs:
        return out
    image, sha = _image_for(session, item)
    with Image.open(io.BytesIO(image)) as im:
        width, height = im.size
    parts = (
        [
            p
            for p in session.scalars(
                select(ItemPart).where(ItemPart.item_id == item.id).order_by(ItemPart.id)
            )
            if not p.removed and p.region_kind in ("mask", "box")
        ]
        if "parts" in needs
        else []
    )
    sam = any(not part_cached(session, sha, p) for p in parts) or (
        "object_mask" in needs and not object_cached(session, item)
    )
    if sam:
        limits.check_and_count(board_id, "analyse")
    empty: AppError | None = None
    try:
        for p in parts:
            try:
                region = locate(session, item.id, p.key)
            except AppError as e:
                if e.code == "REGION_EMPTY":
                    continue
                raise
            if region.kind == "mask" and region.mask_url:
                mask = _mask_from_url(region.mask_url, height, width)
            elif region.box:
                mask = _box_mask(region.box, height, width)
            else:
                continue
            out["parts"].append((p.key, p.label, mask))
        if "object_mask" in needs:
            try:
                region = locate_object(session, item.id)
                assert region.mask_url
                out["object"] = _mask_from_url(region.mask_url, height, width)
            except AppError as e:
                if e.code != "REGION_EMPTY":
                    raise
                empty = e
    except Exception:
        if sam:
            limits.refund(board_id, "analyse")
        raise
    if empty is not None or (not out["parts"] and out["object"] is None):
        # nothing usable came out: the person got nothing, so the slot is given back
        if sam:
            limits.refund(board_id, "analyse")
        if empty is not None:
            raise empty
    return out
