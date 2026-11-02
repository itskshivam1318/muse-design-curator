"""The person's edits to an item's labels: parts, dimensions and the content type.

Everything written here is the person's: parts are marked source "you", dimension rows source
"user", so the analysis merge never overwrites or re-adds them. Each edit leaves an event.
"""

import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.spec import spec_for, spec_from_dimension
from app.analysis.types import AttrKind, DimensionOut, DimType, Region
from app.db.models import CONTENT_TYPES, BoardItem, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.errors import AppError
from app.extraction.service import _require_item

MAX_KEY = 40


def _snake(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:MAX_KEY].strip("_")
    if not key:
        raise AppError(400, "VALIDATION_ERROR", "A label needs letters or digits")
    return key


def _part_row(session: Session, item_id: str, key: str) -> ItemPart | None:
    return session.scalar(select(ItemPart).where(ItemPart.item_id == item_id, ItemPart.key == key))


def _live_part(session: Session, item_id: str, key: str) -> ItemPart:
    part = _part_row(session, item_id, key)
    if part is None or part.removed:
        raise AppError(404, "PART_NOT_FOUND", "Part not found")
    return part


def _row(session: Session, item_id: str, key: str) -> ItemAttribute | None:
    return next((r for r in attrs_repo.for_item(session, item_id) if r.key == key), None)


def _live_row(session: Session, item_id: str, key: str) -> ItemAttribute:
    row = _row(session, item_id, key)
    if row is None or row.removed:
        raise AppError(404, "UNKNOWN_ATTRIBUTE", f"{key!r} is not a dimension of this item")
    return row


def _part_json(p: ItemPart | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"label": p.label, "region_kind": p.region_kind, "region": p.region_json,
            "removed": p.removed}  # fmt: skip


def _dim_json(r: ItemAttribute | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"label": r.label, "type": r.dim_type, "part": r.part, "prompt": r.prompt,
            "removed": r.removed}  # fmt: skip


def _event(session: Session, item_id: str, key: str, action: str, before: Any, after: Any) -> None:
    attrs_repo.append_event(
        session, item_id=item_id, key=key, actor="user", action=action,
        before_json=before, after_json=after,
    )  # fmt: skip


def default_prompt(label: str) -> str:
    """The question an abstract dimension asks when the person gave only its name."""
    return f"What is the {label} of this item?"


# ---- parts ----


def add_part(session: Session, item_id: str, label: str, region: Region | None) -> ItemPart:
    """Add (or bring back) a part. No region on an image: it is located from the label later.
    A UI screenshot's part needs its box (no segmentation for UI), a note's its text range."""
    item = _require_item(session, item_id)
    key = _snake(label)
    if region is None and item.kind == "note":
        raise AppError(400, "VALIDATION_ERROR", "A part of a note needs a text range")
    if region is None and item.content_type == "ui":
        raise AppError(422, "REGION_REQUIRED", "A part of a UI screenshot needs its box")
    if region is not None and (region.kind == "text_range") != (item.kind == "note"):
        raise AppError(
            422, "REGION_KIND_MISMATCH", f"A {region.kind} region does not fit this item"
        )
    kind = region.kind if region is not None else "mask"
    if region is None:
        value: Any = None
    elif region.kind == "text_range":
        value = region.range
    else:
        value = region.box
    if value is None and region is not None:
        raise AppError(400, "VALIDATION_ERROR", f"A {region.kind} part needs its region")
    part = _part_row(session, item_id, key)
    if part is not None and not part.removed:
        raise AppError(409, "PART_EXISTS", f"This item already has a part {key!r}")
    before = _part_json(part)
    if part is None:
        part = ItemPart(item_id=item.id, key=key, label=label, region_kind=kind, source="you")
        session.add(part)
    part.label, part.region_kind, part.region_json = label, kind, value
    part.mask_path, part.source, part.removed = None, "you", False
    session.flush()
    _event(session, item_id, key, "edited", before, _part_json(part))
    return part


def rename_part(session: Session, item_id: str, key: str, label: str) -> ItemPart:
    """Rename a part. Its key stays, so dimensions keep pointing at it; a mask is re-located."""
    _require_item(session, item_id)
    part = _live_part(session, item_id, key)
    before = _part_json(part)
    if part.region_kind == "mask" and label != part.label:
        part.mask_path = None
    part.label, part.source = label, "you"
    session.flush()
    _event(session, item_id, key, "edited", before, _part_json(part))
    return part


def remove_part(session: Session, item_id: str, key: str) -> None:
    """Remove a part and the dimensions that read it; neither comes back on re-analysis."""
    _require_item(session, item_id)
    part = _live_part(session, item_id, key)
    before = _part_json(part)
    part.removed, part.source = True, "you"
    for row in attrs_repo.for_item(session, item_id):
        if row.part == key and not row.removed:
            before_dim = _dim_json(row)
            row.removed = True
            _event(session, item_id, row.key, "disabled", before_dim, _dim_json(row))
    session.flush()
    _event(session, item_id, key, "disabled", before, _part_json(part))


# ---- dimensions ----


def _dimension(
    key: str,
    label: str,
    type_: DimType,
    part: str | None,
    prompt: str | None,
    kind: AttrKind,
    **extra: Any,
) -> DimensionOut:
    try:
        return DimensionOut(
            key=key, label=label, type=type_, part=part, prompt=prompt, kind=kind,
            confidence=0.0, **extra,
        )  # fmt: skip
    except ValidationError as e:
        raise AppError(400, "VALIDATION_ERROR", str(e.errors()[0]["msg"])) from e


def add_dimension(
    session: Session, item_id: str, label: str, type: DimType, part: str | None,
    prompt: str | None, kind: AttrKind = "text",
) -> ItemAttribute:  # fmt: skip
    """Add (or bring back) a dimension of this item. Its value is empty until someone sets it.
    An abstract dimension added by name alone asks the default question about its label."""
    _require_item(session, item_id)
    key = _snake(label)
    if type == "abstract" and not (prompt and prompt.strip()):
        prompt = default_prompt(label)
    if part is not None:
        _live_part(session, item_id, part)
    d = _dimension(key, label, type, part, prompt, kind)
    row = _row(session, item_id, key)
    if row is not None and not row.removed:
        raise AppError(409, "DIMENSION_EXISTS", f"This item already has a dimension {key!r}")
    before = _dim_json(row)
    row = attrs_repo.upsert(
        session, item_id, key,
        label=label, category=type, kind=kind, part=part, value_json=None, confidence=0.0,
        status="missing", source="user", source_detail="", dim_type=type, prompt=prompt,
        spec_json=spec_from_dimension(d).model_dump(mode="json"), removed=False,
        model_value_json=None, model_confidence=None, enabled=True,
    )  # fmt: skip
    _event(session, item_id, key, "edited", before, _dim_json(row))
    return row


def update_dimension(
    session: Session, item_id: str, key: str, *, label: str | None = None,
    type: DimType | None = None, part: str | None = None, prompt: str | None = None,
) -> ItemAttribute:  # fmt: skip
    """Change a dimension's label, type, part or prompt (None leaves it). Its key stays."""
    _require_item(session, item_id)
    row = _live_row(session, item_id, key)
    new_type: DimType = type or ("physical" if row.dim_type == "physical" else "abstract")
    new_part = None if new_type == "abstract" else (part or row.part)
    new_prompt = prompt if prompt is not None else row.prompt
    new_label = label or row.label
    if new_part is not None:
        _live_part(session, item_id, new_part)
    old = spec_for(row)
    extra = {
        "vocabulary": getattr(old, "vocabulary", None) or [],
        "scale": getattr(old, "scale", None) or [],
        "min": getattr(old, "min", None), "max": getattr(old, "max", None),
        "unit": getattr(old, "unit", None),
    }  # fmt: skip
    d = _dimension(key, new_label, new_type, new_part, new_prompt, row.kind, **extra)  # type: ignore[arg-type]
    before = _dim_json(row)
    row = attrs_repo.upsert(
        session, item_id, key,
        label=new_label, category=new_type, part=new_part, dim_type=new_type, prompt=new_prompt,
        spec_json=spec_from_dimension(d).model_dump(mode="json"), source="user",
    )  # fmt: skip
    _event(session, item_id, key, "edited", before, _dim_json(row))
    return row


def remove_dimension(session: Session, item_id: str, key: str) -> None:
    _require_item(session, item_id)
    row = _live_row(session, item_id, key)
    before = _dim_json(row)
    row.removed = True
    session.flush()
    _event(session, item_id, key, "disabled", before, _dim_json(row))


# ---- content type ----


def set_content_type(session: Session, item_id: str, content_type: str) -> BoardItem:
    """Correct what the item is, then analyse it again as that."""
    from app.analysis.service import request_analyse

    item = _require_item(session, item_id)
    if content_type not in CONTENT_TYPES:
        raise AppError(400, "VALIDATION_ERROR", f"content_type must be one of {CONTENT_TYPES}")
    item.content_type, item.content_type_locked = content_type, True
    session.flush()
    request_analyse(session, item_id)
    return item


__all__ = [
    "add_dimension", "add_part", "default_prompt", "remove_dimension", "remove_part", "rename_part",
    "set_content_type", "update_dimension",
]  # fmt: skip
