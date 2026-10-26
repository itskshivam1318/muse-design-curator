"""Keep / reject decisions on variation candidates. Decisions are append-only; nothing here
writes project preferences."""

import hashlib
import io
import json
from functools import partial
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from app import events
from app.api.schemas import item_to_dict
from app.board import profile_hook
from app.db.models import BoardItem, CorpusItem, Decision, RunCandidate, VariationRun
from app.db.repos import attributes as attrs_repo
from app.db.repos import corpus as corpus_repo
from app.db.repos import decisions as decisions_repo
from app.db.repos import idempotency as idem_repo
from app.db.repos import items as items_repo
from app.db.repos import lenses as lenses_repo
from app.db.repos import runs as runs_repo
from app.db.session import after_commit
from app.domain.attributes import RELIABLE_CONFIDENCE
from app.domain.lens import LensSpec
from app.errors import AppError
from app.ingest.common import GAP, default_size
from app.ingest.images import existing_by_sha
from app.ingest.sniff import sniff_image
from app.storage import files

REJECT_REASONS = [
    "wrong_target_change", "protected_changed", "image_quality", "not_on_brief",
    "duplicate_feel", "not_my_style", "other",
]  # fmt: skip
DECIDABLE = ("validated", "uncertain")
NOTE_MAX = 500


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _check_args(
    decision: str, reason_code: str | None, note: str | None, mark_not_this: bool
) -> None:
    if decision not in ("keep", "reject"):
        raise AppError(400, "INVALID_DECISION", "decision must be 'keep' or 'reject'")
    if decision == "keep" and (reason_code or note or mark_not_this):
        raise AppError(
            400, "REASON_ONLY_ON_REJECT", "reason, note and mark_not_this apply to reject"
        )
    if reason_code is not None and reason_code not in REJECT_REASONS:
        raise AppError(400, "INVALID_REASON_CODE", "Unknown reason code", REJECT_REASONS)
    if note is not None and len(note) > NOTE_MAX:
        raise AppError(400, "NOTE_TOO_LONG", f"note must be at most {NOTE_MAX} characters")


def decision_dict(d: Decision) -> dict[str, Any]:
    return {
        "id": d.id, "decision": d.decision, "reason_code": d.reason_code, "note": d.note,
        "item_id": d.item_id, "created_at": d.created_at,
    }  # fmt: skip


def _kept_item(session: Session, candidate_id: str) -> BoardItem | None:
    for d in decisions_repo.history(session, candidate_id):
        if d.item_id:
            item = items_repo.get(session, d.item_id)
            if item is not None and item.removed_at is None:
                return item
    return None


def _copy_attributes(session: Session, item: BoardItem, cx: CorpusItem, lens: LensSpec) -> None:
    by_key = {a.key: a for a in lens.attributes}
    for row in corpus_repo.attributes(session, cx.id):
        spec = by_key.get(row.key)
        if spec is None:
            continue
        if row.value_json is None:
            status = "missing"
        elif row.confidence < RELIABLE_CONFIDENCE:
            status = "uncertain"
        else:
            status = "extracted"
        attrs_repo.upsert(
            session, item.id, row.key, label=spec.label, category=spec.category,
            kind=spec.kind, part=spec.part, value_json=row.value_json,
            confidence=row.confidence, status=status, source="corpus_index",
            evidence_json=row.evidence_json, measured_json=row.measured_json,
        )  # fmt: skip


def _create_item(
    session: Session, run: VariationRun, cx: CorpusItem, role: str
) -> tuple[BoardItem, bool]:
    if not cx.local_path or not files.abs_path(cx.local_path).is_file():
        raise AppError(409, "CANDIDATE_IMAGE_MISSING", "The candidate image is not available")
    data = files.abs_path(cx.local_path).read_bytes()
    sha = files.sha256_hex(data)
    dup = existing_by_sha(session, run.board_id, sha)
    if dup is not None:
        return dup, False
    sniffed = sniff_image(data)
    if sniffed is None:
        raise AppError(409, "CANDIDATE_IMAGE_MISSING", "The candidate image is not available")
    mime, ext = sniffed
    img = Image.open(io.BytesIO(data))
    img.load()
    storage = files.save_original(data, sha, ext)
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    parent = items_repo.get(session, run.source_item_id)
    active = items_repo.list_active(session, run.board_id)
    z = max((i.z for i in active), default=-1) + 1
    x, y = (parent.x + parent.w + GAP, parent.y) if parent is not None else (0.0, 0.0)
    item = items_repo.create(
        session, board_id=run.board_id, kind="image", origin="candidate", sha256=sha,
        storage_path=storage, thumb_path=thumb, mime=mime, width=img.size[0],
        height=img.size[1], rights_status="licensed", corpus_item_id=cx.id,
        parent_item_id=run.source_item_id, parse_status="completed", role=role,
        x=x, y=y, w=w, h=h, z=z, source_url=cx.image_url, page_url=cx.landing_url,
        creator_handle=cx.creator_name,
    )  # fmt: skip
    lens_row = lenses_repo.get(session, run.lens_id)
    if lens_row is not None:
        _copy_attributes(session, item, cx, LensSpec.model_validate(lens_row.spec_json))
    return item, True


def _publish(board_id: str, data: dict[str, Any]) -> None:
    events.publish(board_id, "item.added", data)


def record_decision(
    session: Session,
    run_id: str,
    candidate_id: str,
    decision: str,
    reason_code: str | None = None,
    note: str | None = None,
    mark_not_this: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    route = f"POST /api/runs/{run_id}/candidates/{candidate_id}/decisions"
    digest = _hash({"d": decision, "r": reason_code, "n": note, "m": mark_not_this})
    if idempotency_key:
        seen = idem_repo.get(session, idempotency_key)
        if seen is not None:
            if seen.route != route or seen.request_hash != digest:
                raise AppError(
                    409, "IDEMPOTENCY_KEY_REUSED",
                    "This Idempotency-Key was already used for a different request",
                )  # fmt: skip
            return dict(seen.response_json)
    run = runs_repo.get(session, run_id)
    cand: RunCandidate | None = runs_repo.get_candidate(session, candidate_id)
    if run is None or cand is None or cand.run_id != run_id:
        raise AppError(404, "CANDIDATE_NOT_FOUND", "Candidate not found in this run")
    _check_args(decision, reason_code, note, mark_not_this)
    if cand.state not in DECIDABLE:
        raise AppError(
            409, "CANDIDATE_NOT_DECIDABLE", "Only validated or uncertain candidates can be decided"
        )
    cx = corpus_repo.get(session, cand.corpus_item_id)
    assert cx is not None
    wants_role = (
        "counter_example"
        if decision == "reject" and mark_not_this
        else "reference"
        if decision == "keep"
        else None
    )
    item = _kept_item(session, candidate_id)
    created = False
    if wants_role is not None:
        if item is None:
            item, created = _create_item(session, run, cx, wants_role)
        elif item.origin == "candidate" and item.role != wants_role:
            item.role = wants_role
            session.flush()
            after_commit(session, partial(_publish_updated, run.board_id, item_to_dict(item)))
    row = decisions_repo.append(
        session, board_id=run.board_id, run_id=run_id, run_candidate_id=candidate_id,
        corpus_item_id=cx.id, decision=decision, reason_code=reason_code, note=note,
        item_id=item.id if (item is not None and wants_role is not None) else None,
    )  # fmt: skip
    if item is not None and wants_role is not None:
        if created:
            after_commit(session, partial(_publish, run.board_id, item_to_dict(item)))
        after_commit(session, partial(profile_hook.request_recompute, run.board_id))
    history = [decision_dict(d) for d in decisions_repo.history(session, candidate_id)]
    out = {
        "decision": decision_dict(row), "history": history,
        "item": item_to_dict(item) if item is not None and wants_role is not None else None,
    }  # fmt: skip
    if idempotency_key:
        idem_repo.put(session, idempotency_key, route, digest, 201, out)
    return out


def _publish_updated(board_id: str, data: dict[str, Any]) -> None:
    events.publish(board_id, "item.updated", data)
