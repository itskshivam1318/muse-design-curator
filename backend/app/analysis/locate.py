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
from app.extraction.service import _fit, _image_for, _mask_rel, _part_mask, _require_item
from app.measure.palette import mask_ratio
from app.providers import get_segmentation
from app.providers.reliability import ModelError
from app.providers.segmentation import SegmentationProvider
from app.storage import files

MAX_PROMPT_WORDS = 3
MIN_MASK_RATIO = 0.001
# a segmented instance must overlap the part's rough box this much (IoU) to be that part
MIN_HINT_IOU = 0.1


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


def _hint(part: ItemPart) -> list[float] | None:
    """The rough box the analysis gave an image part (or its last located box), if any."""
    r = part.region_json
    if not isinstance(r, list) or len(r) != 4:
        return None
    return [float(v) for v in r]


def _box_mask(box: list[float], height: int, width: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=bool)
    x0, y0 = int(box[0] * width), int(box[1] * height)
    x1, y1 = int(np.ceil(box[2] * width)), int(np.ceil(box[3] * height))
    mask[y0:y1, x0:x1] = True
    return mask


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.count_nonzero(a | b)
    return np.count_nonzero(a & b) / union if union else 0.0


def _bbox(mask: np.ndarray) -> list[float]:
    ys, xs = np.nonzero(mask)
    height, width = mask.shape
    return [xs.min() / width, ys.min() / height, (xs.max() + 1) / width, (ys.max() + 1) / height]


def _hinted_mask(
    seg: SegmentationProvider, image: bytes, sha: str, prompt: str, hint: list[float],
    size: tuple[int, int],
) -> tuple[np.ndarray, str]:  # fmt: skip
    """The segmented instance that overlaps the part's rough box best; the box itself when none
    does. A text prompt cannot tell the rear wheel from the front one, the analysis box can.
    Saved under its own name: the (sha, prompt) cache keeps only the best-scored instance."""
    height, width = size
    box = _box_mask(hint, height, width)
    res = seg.localize(image, sha, prompt)
    masks = [_fit(i.mask, height, width) for i in res.instances] if res.found else []
    best = max(masks, key=lambda m: _iou(m, box), default=None)
    mask = best if best is not None and _iou(best, box) >= MIN_HINT_IOU else box
    rel = _mask_rel(sha, f"{prompt}@{','.join(f'{c:.3f}' for c in hint)}")
    path = files.abs_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask.astype(np.uint8) * 255).save(path, "PNG")
    return mask, rel


def locate(session: Session, item_id: str, part_key: str) -> Region:
    """The region of one part; a mask part is segmented on first use and cached."""
    item = _require_item(session, item_id)
    part = _part(session, item.id, part_key)
    if part.region_kind == "box":
        return Region(kind="box", box=part.region_json)
    if part.region_kind == "text_range":
        return Region(kind="text_range", range=part.region_json)
    if part.mask_path and files.abs_path(part.mask_path).is_file():
        return _mask_region(part)
    part.mask_path = None  # never located, or its cached file is gone: locate it (again)

    image, sha = _image_for(session, item)
    prompt = " ".join(part.label.split()[:MAX_PROMPT_WORDS])
    hint = _hint(part)
    mask: np.ndarray | None
    try:
        seg = get_segmentation(get_settings())
        with Image.open(io.BytesIO(image)) as im:
            width, height = im.size
        if hint is not None:
            mask, rel = _hinted_mask(seg, image, sha, prompt, hint, (height, width))
            bbox = tuple(_bbox(mask)) if mask.any() else None
        else:
            mask, bbox = _part_mask(session, seg, image, sha, prompt, (height, width))
            rel = _mask_rel(sha, prompt)
    except ModelError as e:
        raise AppError(502, "REGION_FAILED", "Could not locate this part") from e
    if mask is None or bbox is None or mask_ratio(mask, np.ones_like(mask)) < MIN_MASK_RATIO:
        raise AppError(422, "REGION_EMPTY", "Nothing found for this part")
    part.mask_path = rel
    part.region_json = [round(c, 6) for c in bbox]
    session.commit()
    return _mask_region(part)
