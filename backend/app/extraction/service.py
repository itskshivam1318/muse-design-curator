"""Lens-driven item parsing: SAM grounds parts, code measures, the reasoning model reads the rest.

User edits always survive: the final merge re-reads the stored rows in its own transaction.
"""

import hashlib
import logging
from functools import partial
from typing import Any

import numpy as np
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import events, jobs
from app.board import profile_hook
from app.config import get_settings
from app.db.models import BoardItem, ItemAttribute
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.repos import masks as masks_repo
from app.db.session import after_commit
from app.domain.attributes import (
    AttributeRecord,
    Evidence,
    ModelAttribute,
    normalize_model_attribute,
    validate_value,
)
from app.domain.kinds import AttributeSpec, NumberSpec
from app.domain.lens import LensSpec
from app.errors import AppError
from app.extraction.merge import merge_extraction, record_fields
from app.extraction.schema import build_extraction_schema, is_measured, model_specs
from app.lens_service import ensure_board_lens
from app.measure.palette import (
    dominant_lab,
    mask_ratio,
    masked_palette,
    nearest_color_name,
    palette_count,
    to_rgb_array,
)
from app.measure.shape import shape_descriptor
from app.notes.service import with_notes
from app.providers import get_embedder, get_reasoning, get_segmentation
from app.providers.reliability import ModelError
from app.storage import files

log = logging.getLogger(__name__)

PROMPT_VERSION = "item-extract-v1"
CLAIMABLE = ("pending", "failed", "completed", "pending_lens")
RETRYABLE = ("failed", "completed", "pending_lens")
MEASURED = "measured"


# ---- helpers ----


def _require_item(session: Session, item_id: str) -> BoardItem:
    item = items_repo.get(session, item_id)
    if item is None or item.removed_at is not None:
        raise AppError(404, "ITEM_NOT_FOUND", "Item not found")
    return item


def current_lens(session: Session, board_id: str) -> LensSpec | None:
    """The board's confirmed lens, read-only (never proposes)."""
    from app.db.repos import lenses as lenses_repo

    board = boards_repo.get(session, board_id)
    row = lenses_repo.get(session, board.lens_id) if board and board.lens_id else None
    return LensSpec.model_validate(row.spec_json) if row is not None else None


def _image_for(session: Session, item: BoardItem) -> tuple[bytes, str]:
    """The bytes parsed for this item and their sha256: the image, or a video's chosen frame."""
    if item.kind == "image" and item.storage_path:
        rel, sha = item.storage_path, item.sha256
    elif item.kind == "video":
        chosen = next((f for f in items_repo.frames(session, item.id) if f.chosen), None)
        if chosen is None:
            raise AppError(400, "NO_USABLE_FRAMES", "Video has no chosen frame")
        rel, sha = chosen.storage_path, chosen.sha256
    else:
        raise AppError(400, "UNSUPPORTED_ITEM", "This item has no image to parse")
    path = files.abs_path(rel)
    if not path.is_file():
        raise AppError(400, "IMAGE_UNAVAILABLE", "The item image is missing from storage")
    data = path.read_bytes()
    return data, sha or files.sha256_hex(data)


def _summary(row: ItemAttribute | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"value": row.value_json, "status": row.status, "confidence": row.confidence}


# ---- masks ----


def _mask_rel(sha: str, prompt: str) -> str:
    return f"masks/{sha}-{hashlib.sha256(prompt.encode()).hexdigest()[:12]}.png"


def _fit(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    if mask.shape == (height, width):
        return mask
    im = Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (width, height), Image.Resampling.NEAREST
    )
    return np.asarray(im) > 127


def _part_mask(
    session: Session, seg: Any, image: bytes, sha: str, prompt: str, size: tuple[int, int]
) -> tuple[np.ndarray | None, tuple[float, float, float, float] | None]:
    """(mask, normalised bbox) for a SAM part, cached by (image sha, prompt). None if absent.

    A newly cached mask row is committed at once (with whatever the caller had pending), so no
    write transaction stays open across the next SAM or model call.
    """
    height, width = size
    row = masks_repo.get(session, sha, prompt)
    if row is None:
        res = seg.localize(image, sha, prompt)
        if not res.found or not res.instances:
            masks_repo.save(session, sha, prompt, found=False, provider=seg.id)
            session.commit()
            return None, None
        best = max(res.instances, key=lambda i: i.score if i.score is not None else 0.0)
        rel = _mask_rel(sha, prompt)
        path = files.abs_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(best.mask.astype(np.uint8) * 255).save(path, "PNG")
        row = masks_repo.save(
            session, sha, prompt, found=True, bbox_json=list(best.bbox), mask_path=rel,
            score=best.score, provider=seg.id,
        )  # fmt: skip
        session.commit()
    if not row.found or not row.mask_path:
        return None, None
    path = files.abs_path(row.mask_path)
    if not path.is_file():
        return None, None
    with Image.open(path) as im:
        mask = _fit(np.asarray(im.convert("L")) > 127, height, width)
    x1, y1, x2, y2 = row.bbox_json
    bbox = (x1 / width, y1 / height, x2 / width, y2 / height)
    return mask, tuple(min(1.0, max(0.0, c)) for c in bbox)  # type: ignore[return-value]


# ---- measurement ----


def _measured(spec: AttributeSpec, value: Any, evidence: Evidence, **extra: Any) -> AttributeRecord:
    return AttributeRecord.model_validate(
        {
            "key": spec.key, "label": spec.label, "category": spec.category, "kind": spec.kind,
            "part": spec.part, "value": value, "confidence": 1.0 if value is not None else 0.0,
            "status": "extracted" if value is not None else "missing", "source": MEASURED,
            "source_detail": "code", "evidence": evidence, **extra,
        }
    )  # fmt: skip


def _missing(spec: AttributeSpec) -> AttributeRecord:
    return _measured(spec, None, Evidence())


def measure_attributes(
    lens: LensSpec, rgb: np.ndarray, grounded: dict[str, tuple[Any, Any]]
) -> list[AttributeRecord]:
    """Colour, mask-ratio / palette-count numbers and (flagged) shape, measured by code."""
    shape_on = get_settings().SHAPE_KIND_ENABLED
    height, width = rgb.shape[:2]
    out: list[AttributeRecord] = []
    for spec in lens.attributes:
        if not is_measured(spec) or (spec.kind == "shape" and not shape_on):
            continue
        if spec.part is not None and spec.part in grounded:
            mask, bbox = grounded[spec.part]
            if mask is None:  # the part was not found: do not measure the wrong region
                out.append(_missing(spec))
                continue
        else:
            mask, bbox = None, None
        evidence = Evidence(kind="measurement", bbox=bbox)
        if spec.kind == "color":
            pal = masked_palette(rgb, mask)
            if not pal:
                out.append(_missing(spec))
                continue
            lab = dominant_lab(pal)
            measured = {"lab": [float(c) for c in lab], "hex": pal[0]["hex"]}
            out.append(_measured(spec, nearest_color_name(lab), evidence, measured=measured))
        elif isinstance(spec, NumberSpec):
            if spec.measure == "mask_ratio":
                full = np.ones((height, width), dtype=bool)
                raw = round(mask_ratio(mask if mask is not None else full, full), 4)
            else:
                raw = float(palette_count(rgb, mask))
            out.append(_measured(spec, validate_value(raw, spec), evidence))
        else:  # shape
            region = mask if mask is not None else np.ones((height, width), dtype=bool)
            try:
                desc = shape_descriptor(region)
            except ValueError:
                out.append(_missing(spec))
                continue
            out.append(_measured(spec, "measured", evidence, measured=desc))
    return out


# ---- model extraction ----


def _prompt(lens: LensSpec, context: str) -> str:
    intro = (
        f"Read the image as a '{lens.label}' reference. For every attribute in the schema give "
        "a value, a confidence from 0 to 1 and evidence (region with a 0..1 bbox, a cue, or "
        "none). Use null with no evidence when the attribute cannot be seen."
    )
    lines = [intro]
    if context.strip():
        lines.append(f"Board context: {context.strip()}")
    return "\n".join(lines)


def _model_records(lens: LensSpec, raw: Any, source: str, detail: str) -> list[AttributeRecord]:
    specs = model_specs(lens.attributes)
    if not specs:
        return []
    if not isinstance(raw, dict) or not any(s.key in raw for s in specs):
        raise ModelError("MODEL_INVALID_RESPONSE", message="response does not match the schema")
    out: list[AttributeRecord] = []
    for spec in specs:
        entry = raw.get(spec.key)
        try:
            if not isinstance(entry, dict):
                raise TypeError("not an object")
            attr = ModelAttribute.model_validate({**entry, "key": spec.key})
        except (ValidationError, TypeError):
            attr = ModelAttribute(key=spec.key, value=None, confidence=0)
        out.append(normalize_model_attribute(attr, spec, source, detail))
    return out


def ground_parts(
    session: Session, lens: LensSpec, image: bytes, sha: str, size: tuple[int, int]
) -> dict[str, tuple[Any, Any]]:
    """SAM-grounded parts of the lens as {part id: (mask, bbox)}; mask is None when not found."""
    seg = get_segmentation(get_settings())
    return {
        part.id: _part_mask(session, seg, image, sha, part.sam_prompt, size)
        for part in lens.parts
        if part.grounding == "sam"
    }


def model_extract(
    session: Session, lens: LensSpec, image: bytes, sha: str, context: str = ""
) -> list[AttributeRecord]:
    """The reasoning model's reading of the lens attributes it owns (cached, normalised)."""
    specs = model_specs(lens.attributes)
    if not specs:
        return []
    from app.providers.cache import cached_call

    provider = get_reasoning(get_settings())
    key_parts = [
        provider.id, provider.model, PROMPT_VERSION, lens.id, sha,
        hashlib.sha256(context.encode()).hexdigest(),
    ]  # fmt: skip
    raw = cached_call(
        session, key_parts, None,
        lambda: provider.extract([image], build_extraction_schema(lens), _prompt(lens, context)),
    )  # fmt: skip
    return _model_records(
        lens, raw, "mock" if provider.is_mock else "model", f"{provider.id}/{provider.model}"
    )


# ---- the job ----


def _publish(board_id: str, type_: str, data: dict[str, Any]) -> None:
    events.publish(board_id, type_, data)


def _announce(session: Session, board_id: str, type_: str, data: dict[str, Any]) -> None:
    after_commit(session, partial(_publish, board_id, type_, data))
    after_commit(session, partial(_recompute, board_id))


def _recompute(board_id: str) -> None:
    profile_hook.request_recompute(board_id)


def _claim(session: Session, item_id: str) -> bool:
    """Compare-and-set to 'processing' in a single UPDATE; True when this caller won."""
    res = session.execute(
        update(BoardItem)
        .where(BoardItem.id == item_id, BoardItem.parse_status.in_(CLAIMABLE))
        .values(
            parse_status="processing", parse_error_code=None,
            parse_attempts=BoardItem.parse_attempts + 1,
        )
    )  # fmt: skip
    return bool(res.rowcount)  # type: ignore[attr-defined]


def parse_item(session: Session, item_id: str) -> None:
    item = _require_item(session, item_id)
    if item.kind == "note":  # a note has no image to read
        return
    board_id = item.board_id
    if not _claim(session, item_id):
        session.rollback()
        raise AppError(409, "PARSE_IN_PROGRESS", "This item is already being parsed")
    session.commit()  # concurrent requests now see 'processing'
    try:
        _run(session, item_id, board_id)
    except ModelError as exc:
        _fail(session, item_id, board_id, exc.code)
    except AppError as exc:
        _fail(session, item_id, board_id, exc.code)
    except Exception:
        log.exception("parse of item %s failed", item_id)
        _fail(session, item_id, board_id, "PARSE_ERROR")


def _fail(session: Session, item_id: str, board_id: str, code: str) -> None:
    session.rollback()
    session.execute(
        update(BoardItem).where(BoardItem.id == item_id)
        .values(parse_status="failed", parse_error_code=code)
    )  # fmt: skip
    _announce(session, board_id, "item.failed", {"item_id": item_id, "error_code": code})
    session.commit()


def _run(session: Session, item_id: str, board_id: str) -> None:
    settings = get_settings()
    item = _require_item(session, item_id)
    image, sha = _image_for(session, item)
    rgb = to_rgb_array(image)

    embedder = get_embedder(settings)
    item.embedding_json = [float(x) for x in embedder.embed_images([image])[0]]
    item.embedder_id = embedder.id
    item.palette_json = masked_palette(rgb, None)
    session.commit()  # the embedding is kept whatever happens next

    try:
        lens = ensure_board_lens(session, board_id)
    except AppError as exc:
        if exc.code != "LENS_AMBIGUOUS":
            raise
        lens = None
    if lens is None:
        session.execute(
            update(BoardItem).where(BoardItem.id == item_id).values(parse_status="pending_lens")
        )
        _announce(
            session, board_id, "item.parsed",
            {"item_id": item_id, "parse_status": "pending_lens", "pending_lens": True},
        )  # fmt: skip
        session.commit()
        return

    grounded = ground_parts(session, lens, image, sha, rgb.shape[:2])
    # whole-image parts are not in `grounded`: their attributes are measured on the full image
    records = measure_attributes(lens, rgb, grounded)
    session.commit()  # release the write lock (masks) before the slow model call

    board = boards_repo.get(session, board_id)
    context = with_notes(session, board_id, (board.context if board else "") or "")
    records += model_extract(session, lens, image, sha, context)
    _finish(session, item_id, board_id, records, sha)


def _finish(
    session: Session, item_id: str, board_id: str, records: list[AttributeRecord], sha: str
) -> None:
    """Final transaction: re-read the stored rows so edits made while we were busy survive."""
    session.expire_all()
    item = _require_item(session, item_id)
    rows, evs = merge_extraction(attrs_repo.for_item(session, item_id), records)
    for fields in rows:
        key = fields.pop("key")
        attrs_repo.upsert(session, item_id, key, **fields)
    for ev in evs:
        attrs_repo.append_event(session, item_id=item_id, **ev)
    stale = _image_for(session, item)[1] != sha  # the chosen frame changed while we worked
    item.parse_status = "pending" if stale else "completed"
    item.parse_error_code = None
    if stale:
        after_commit(session, partial(jobs.enqueue, "parse_item", item_id=item_id))
    _announce(
        session, board_id, "item.parsed", {"item_id": item_id, "parse_status": item.parse_status}
    )
    session.commit()


def request_parse(session: Session, item_id: str) -> bool:
    """Queue a (re-)parse unless one is running. False when the item is processing."""
    res = session.execute(
        update(BoardItem)
        .where(
            BoardItem.id == item_id,
            BoardItem.kind != "note",
            BoardItem.parse_status.in_((*RETRYABLE, "pending")),
        )
        .values(parse_status="pending")
    )  # fmt: skip
    if not res.rowcount:  # type: ignore[attr-defined]
        return False
    after_commit(session, partial(jobs.enqueue, "parse_item", item_id=item_id))
    return True


def parse_item_job(item_id: str) -> None:
    from app.api import deps

    with deps._factory()() as session:
        try:
            parse_item(session, item_id)
        except AppError as exc:
            if exc.code != "PARSE_IN_PROGRESS":
                raise
        session.commit()


jobs.register("parse_item", parse_item_job)


# ---- user edits ----

_UNSET: Any = object()


def edit_attribute(
    session: Session, item_id: str, key: str, value: Any = _UNSET, action: str | None = None
) -> ItemAttribute:
    item = _require_item(session, item_id)
    lens = current_lens(session, item.board_id)
    spec = next((a for a in lens.attributes if a.key == key), None) if lens else None
    if spec is None:
        raise AppError(404, "UNKNOWN_ATTRIBUTE", f"{key!r} is not an attribute of this lens")
    row = next((r for r in attrs_repo.for_item(session, item_id) if r.key == key), None)
    before = _summary(row)
    if action in ("disable", "enable"):
        if value is not _UNSET:
            raise AppError(400, "VALIDATION_ERROR", f"{action} takes no value")
        fields: dict[str, Any] = {"enabled": action == "enable"}
        event = "disabled" if action == "disable" else "enabled"
    elif value is _UNSET and action != "confirm":
        raise AppError(400, "VALIDATION_ERROR", "Send a value or an action")
    else:
        if value is _UNSET:
            new = row.value_json if row is not None else None
            if new is None:
                raise AppError(400, "INVALID_ATTRIBUTE_VALUE", "There is no value to confirm")
        else:
            new = validate_value(value, spec)
            if value is not None and new is None:
                raise AppError(
                    400, "INVALID_ATTRIBUTE_VALUE", f"Value does not fit attribute {key!r}"
                )
        event = "confirmed" if action == "confirm" else "edited"
        fields = {
            "value_json": new, "confidence": 1.0, "status": event, "source": "user",
            "source_detail": "", "evidence_json": Evidence().model_dump(mode="json"),
        }  # fmt: skip
    if row is None:
        base = AttributeRecord(
            key=key, label=spec.label, category=spec.category, kind=spec.kind, part=spec.part,
            confidence=0, status="missing", source="user",
        )  # fmt: skip
        fields = {**record_fields(base), **fields}
    row = attrs_repo.upsert(session, item_id, key, **fields)
    attrs_repo.append_event(
        session, item_id=item_id, key=key, actor="user", action=event,
        before_json=before, after_json=_summary(row),
    )  # fmt: skip
    after_commit(session, partial(_recompute, item.board_id))
    return row


def attribute_to_dict(row: ItemAttribute) -> dict[str, Any]:
    return {
        "key": row.key, "label": row.label, "category": row.category, "kind": row.kind,
        "part": row.part, "value": row.value_json, "confidence": row.confidence,
        "status": row.status, "source": row.source, "source_detail": row.source_detail,
        "evidence": row.evidence_json, "enabled": row.enabled,
        "measured": row.measured_json, "model_value": row.model_value_json,
        "model_confidence": row.model_confidence, "updated_at": row.updated_at,
    }  # fmt: skip


def provider_info() -> dict[str, Any]:
    settings = get_settings()
    try:
        p = get_reasoning(settings)
    except ModelError:
        return {"id": settings.REASONING_PROVIDER, "model": None, "is_mock": False}
    return {"id": p.id, "model": p.model, "is_mock": p.is_mock}


__all__ = [
    "attribute_to_dict", "current_lens", "edit_attribute", "ground_parts", "measure_attributes",
    "model_extract", "parse_item", "parse_item_job", "provider_info", "request_parse",
]  # fmt: skip
