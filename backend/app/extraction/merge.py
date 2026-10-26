"""Merge freshly extracted attributes into the stored rows without losing user work."""

from typing import Any

from app.db.models import ItemAttribute
from app.domain.attributes import AttributeRecord

USER_STATUSES = ("edited", "confirmed")


def _summary(value: Any, status: str, confidence: float) -> dict[str, Any]:
    return {"value": value, "status": status, "confidence": confidence}


def _is_user_owned(row: ItemAttribute) -> bool:
    return row.status in USER_STATUSES or not row.enabled


def record_fields(rec: AttributeRecord) -> dict[str, Any]:
    return {
        "label": rec.label, "category": rec.category, "kind": rec.kind, "part": rec.part,
        "value_json": rec.value, "confidence": rec.confidence, "status": rec.status,
        "source": rec.source, "source_detail": rec.source_detail,
        "evidence_json": rec.evidence.model_dump(mode="json"), "measured_json": rec.measured,
        "model_value_json": None, "model_confidence": None,
    }  # fmt: skip


def merge_extraction(
    existing: list[ItemAttribute], incoming: list[AttributeRecord]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (row field dicts to upsert, attribute event dicts to append)."""
    by_key = {r.key: r for r in existing}
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for rec in incoming:
        cur = by_key.get(rec.key)
        if cur is not None and _is_user_owned(cur):
            rows.append(
                {"key": rec.key, "model_value_json": rec.value, "model_confidence": rec.confidence}
            )
            if rec.value != cur.value_json:
                events.append(
                    {"key": rec.key, "actor": "model", "action": "model_suppressed",
                     "before_json": _summary(cur.value_json, cur.status, cur.confidence),
                     "after_json": _summary(rec.value, rec.status, rec.confidence)}
                )  # fmt: skip
            continue
        rows.append({"key": rec.key, **record_fields(rec)})
        before = _summary(cur.value_json, cur.status, cur.confidence) if cur is not None else None
        after = _summary(rec.value, rec.status, rec.confidence)
        if before != after:
            events.append(
                {"key": rec.key, "actor": "model", "action": "extracted",
                 "before_json": before, "after_json": after}
            )  # fmt: skip
    return rows, events
