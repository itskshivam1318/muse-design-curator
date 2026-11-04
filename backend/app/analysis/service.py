"""Analyse an item: one model call names its parts and reads its dimensions.

The merge keeps everything the user wrote or removed; the final transaction re-reads the stored
rows so edits made while the model was busy survive.
"""

import hashlib
import logging
from functools import partial
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import events, jobs
from app.analysis import limits
from app.analysis.analysers import load_content, run_analyser
from app.analysis.context import USER_SOURCES, board_context, hints_for, refresh_learned
from app.analysis.spec import spec_from_dimension
from app.analysis.types import Analysis
from app.board import profile_hook
from app.config import get_settings
from app.db.models import BoardItem, Exploration, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.session import after_commit
from app.domain.attributes import RELIABLE_CONFIDENCE
from app.errors import AppError
from app.extraction.service import RETRYABLE, _claim, _image_for, _require_item
from app.measure.palette import masked_palette, to_rgb_array
from app.providers import get_embedder
from app.providers.reliability import ModelError

log = logging.getLogger(__name__)


# ---- merge ----


def _summary(row: ItemAttribute) -> dict[str, Any]:
    return {"value": row.value_json, "status": row.status, "confidence": row.confidence}


def merge_analysis(session: Session, item: BoardItem, a: Analysis) -> None:
    """Write the analysis. User rows and parts are untouched; removed ones are never re-added;
    AI rows the analysis no longer has are deleted, or marked stale when they were explored."""
    if not item.content_type_locked:  # the person said what this item is
        item.content_type = a.content_type
    item.subject = a.subject or None  # overwritten on every re-analysis
    _merge_dimensions(session, item, a)
    _merge_parts(session, item, a)


def _merge_dimensions(session: Session, item: BoardItem, a: Analysis) -> None:
    rows = {r.key: r for r in attrs_repo.for_item(session, item.id)}
    explored = set(session.scalars(select(Exploration.key).where(Exploration.item_id == item.id)))
    seen: set[str] = set()
    for d in a.dimensions:
        if d.key in seen:
            continue
        seen.add(d.key)
        row = rows.get(d.key)
        if row is not None and (row.removed or row.source in USER_SOURCES):
            continue
        before = _summary(row) if row is not None else None
        status = "extracted" if d.confidence >= RELIABLE_CONFIDENCE else "uncertain"
        saved = attrs_repo.upsert(
            session, item.id, d.key,
            label=d.label, category=d.type, kind=d.kind, part=d.part, value_json=d.value,
            confidence=d.confidence, status=status, source="model", dim_type=d.type,
            prompt=d.prompt, spec_json=spec_from_dimension(d).model_dump(mode="json"),
            model_value_json=d.value, model_confidence=d.confidence,
        )  # fmt: skip
        if before != _summary(saved):
            attrs_repo.append_event(
                session, item_id=item.id, key=d.key, actor="model", action="extracted",
                before_json=before, after_json=_summary(saved),
            )  # fmt: skip
    for key, row in rows.items():
        if key in seen or row.removed or row.source in USER_SOURCES:
            continue
        if key in explored:  # an old dimension, not found on this item, but it has been explored
            row.status = "stale"
        else:
            session.delete(row)
    session.flush()


def _merge_parts(session: Session, item: BoardItem, a: Analysis) -> None:
    rows = {p.key: p for p in session.scalars(select(ItemPart).where(ItemPart.item_id == item.id))}
    seen: set[str] = set()
    for p in a.parts:
        seen.add(p.key)
        row = rows.get(p.key)
        if row is None:
            session.add(
                ItemPart(
                    item_id=item.id,
                    key=p.key,
                    label=p.label,
                    region_kind=p.region_kind,
                    region_json=p.region,
                    source="ai",
                )
            )
        elif row.source == "ai" and not row.removed:
            if (row.region_kind, row.region_json) != (p.region_kind, p.region):
                row.mask_path = None
            row.label, row.region_kind, row.region_json = p.label, p.region_kind, p.region
    kept = {r.part for r in attrs_repo.for_item(session, item.id) if r.part}
    for key, row in rows.items():
        if key not in seen and row.source == "ai" and not row.removed and key not in kept:
            session.delete(row)
    session.flush()


# ---- the job ----


def _fingerprint(session: Session, item: BoardItem) -> str:
    """What the analysis was read from: the image (or chosen frame) or the note text."""
    if item.kind == "note":
        return hashlib.sha256((item.note_text or "").encode()).hexdigest()
    return _image_for(session, item)[1]


def _announce(session: Session, board_id: str, type_: str, data: dict[str, Any]) -> None:
    after_commit(session, partial(events.publish, board_id, type_, data))
    after_commit(session, partial(profile_hook.request_recompute, board_id))


def _fail(session: Session, item_id: str, board_id: str, code: str) -> None:
    session.rollback()
    session.execute(
        update(BoardItem).where(BoardItem.id == item_id)
        .values(parse_status="failed", parse_error_code=code)
    )  # fmt: skip
    _announce(session, board_id, "item.failed", {"item_id": item_id, "error_code": code})
    session.commit()


def analyse(session: Session, item_id: str) -> Analysis | None:
    """Analyse the item now. None when it failed (the item is then marked failed, not raised)."""
    item = _require_item(session, item_id)
    board_id = item.board_id
    if not _claim(session, item_id):
        session.rollback()
        raise AppError(409, "PARSE_IN_PROGRESS", "This item is already being analysed")
    session.commit()  # concurrent requests now see 'processing'
    try:
        result = _run(session, item_id, board_id)
    except (ModelError, AppError) as exc:
        _fail(session, item_id, board_id, exc.code)
        return None
    except Exception:
        log.exception("analysis of item %s failed", item_id)
        _fail(session, item_id, board_id, "PARSE_ERROR")
        return None
    try:
        refresh_learned(session, board_id)
        session.commit()
    except Exception:
        session.rollback()
        log.exception("refreshing learned dimensions for board %s failed", board_id)
    return result


def _run(session: Session, item_id: str, board_id: str) -> Analysis:
    item = _require_item(session, item_id)
    content = load_content(session, item)
    fingerprint = _fingerprint(session, item)
    if content.image is not None:  # the embedding and palette feed the board profile
        embedder = get_embedder(get_settings())
        item.embedding_json = [float(x) for x in embedder.embed_images([content.image])[0]]
        item.embedder_id = embedder.id
        item.palette_json = masked_palette(to_rgb_array(content.image), None)
    context = board_context(session, board_id)
    hints = hints_for(session, board_id, item_id)
    session.commit()  # release the write lock before the slow model call

    analysis = run_analyser(content, context, hints)

    session.expire_all()  # edits made while the model was busy must survive the merge
    item = _require_item(session, item_id)
    merge_analysis(session, item, analysis)
    stale = _fingerprint(session, item) != fingerprint
    item.parse_status = "pending" if stale else "completed"
    item.parse_error_code = None
    if stale:
        after_commit(session, partial(jobs.enqueue, "analyse_item", item_id=item_id))
    _announce(
        session, board_id, "item.parsed", {"item_id": item_id, "parse_status": item.parse_status}
    )
    after_commit(session, partial(events.publish, board_id, "item.analysed", {"item_id": item_id}))
    session.commit()
    return analysis


def queue_analyse(session: Session, item_id: str, *, count: bool = True) -> bool:
    """Queue an analysis unless one is queued or running. False when the item is pending or
    processing: no second job and no second slot (a running job re-queues itself when the
    item changed while it read it).

    `count` takes a slot of the board's daily analyse allowance (429 when it is used up); the
    system's own re-queues (note saves, extracted parts) pass False."""
    item = session.get(BoardItem, item_id)
    if item is None:
        return False
    if item.parse_status in ("pending", "processing"):
        return False
    if count:
        limits.check_and_count(item.board_id, "analyse")
    res = session.execute(
        update(BoardItem)
        .where(BoardItem.id == item_id, BoardItem.parse_status.in_(RETRYABLE))
        .values(parse_status="pending")
    )  # fmt: skip
    if not res.rowcount:  # type: ignore[attr-defined]
        if count:
            limits.refund(item.board_id, "analyse")
        return False
    after_commit(session, partial(jobs.enqueue, "analyse_item", item_id=item_id))
    return True


def request_analyse(session: Session, item_id: str, *, count: bool = True) -> None:
    queue_analyse(session, item_id, count=count)


def recover_stuck_analyses(session: Session) -> int:
    """Startup: queued jobs die with the process, so every live item left `pending` or
    `processing` goes back to `pending` and is queued again (uncounted: it was counted when
    first requested). `pending_lens` and `failed` items wait for a Re-analyse."""
    ids = list(
        session.scalars(
            select(BoardItem.id).where(
                BoardItem.parse_status.in_(("pending", "processing")),
                BoardItem.removed_at.is_(None),
            )
        )
    )
    for item_id in ids:
        session.execute(
            update(BoardItem).where(BoardItem.id == item_id).values(parse_status="pending")
        )
        after_commit(session, partial(jobs.enqueue, "analyse_item", item_id=item_id))
    session.flush()
    return len(ids)


def analyse_item_job(item_id: str) -> None:
    from app.api import deps

    with deps._factory()() as session:
        try:
            analyse(session, item_id)
        except AppError as exc:
            if exc.code != "PARSE_IN_PROGRESS":
                raise
        session.commit()


jobs.register("analyse_item", analyse_item_job)

__all__ = [
    "analyse",
    "analyse_item_job",
    "merge_analysis",
    "queue_analyse",
    "recover_stuck_analyses",
    "request_analyse",
]  # fmt: skip
