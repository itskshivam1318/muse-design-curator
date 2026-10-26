"""Variation runs: create (validate + snapshot), then retrieve, validate and select in the background.

Each stage commits so polling sees progress; progress events go out after the commit.
"""

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app import events, jobs
from app.config import get_settings
from app.db.models import VariationRun
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import idempotency as idem_repo
from app.db.repos import items as items_repo
from app.db.repos import lenses as lenses_repo
from app.db.repos import profiles as profiles_repo
from app.db.repos import runs as runs_repo
from app.db.session import after_commit
from app.domain.attributes import AttributeRecord, Evidence
from app.domain.lens import LensSpec
from app.domain.variation import Nudge, VariationRequest, VariationSpec, validate_variation
from app.errors import AppError
from app.providers import get_reasoning, get_segmentation
from app.providers.reliability import ModelError
from app.retrieval.config import RANKING_CONFIG, RankingConfig
from app.retrieval.filters import apply_exclusions, on_board_from_items, source_from_board_item
from app.retrieval.pool import build_pool
from app.retrieval.scores import Candidate, score_candidate
from app.retrieval.select import select_diverse, shortlist
from app.runs.summary import summarize_run
from app.validation.comparators import AttrValue
from app.validation.validator import (
    MAX_CANDIDATES_PER_CALL,
    VALIDATOR_VERSION,
    CandidateValidation,
    Providers,
    validate_shortlist,
)

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=5)
TERMINAL = ("completed", "failed")
JOB = "run_variation"


# ---- source ----


def source_records(session: Session, item_id: str) -> list[AttributeRecord]:
    """The source item's attributes as the engine uses them, measured data included."""
    out = []
    for r in attrs_repo.for_item(session, item_id):
        out.append(
            AttributeRecord.model_validate({
                "key": r.key, "label": r.label, "category": r.category, "kind": r.kind,
                "part": r.part, "value": r.value_json, "confidence": r.confidence,
                "status": r.status, "source": r.source, "source_detail": r.source_detail or "",
                "evidence": Evidence.model_validate(r.evidence_json or {}),
                "enabled": r.enabled, "measured": r.measured_json,
            })
        )  # fmt: skip
    return out


def _request_of(run: VariationRun) -> VariationRequest:
    return VariationRequest(
        source_item_id=run.source_item_id, target_key=run.target_key, mode=run.mode,  # type: ignore[arg-type]
        target_values=list(run.target_values_json or []),
        protected_keys=list(run.protected_keys_json or []),
        nudge=Nudge.model_validate(run.nudge_json) if run.nudge_json else None,
    )  # fmt: skip


def _provider_snapshot() -> dict[str, Any]:
    s = get_settings()
    try:
        r = get_reasoning(s)
        reasoning = {"id": r.id, "model": r.model, "is_mock": r.is_mock}
    except ModelError:
        reasoning = {"id": s.REASONING_PROVIDER, "model": None, "is_mock": False}
    seg = s.SEGMENTATION_PROVIDER.replace("_", "-")
    return {
        "reasoning": reasoning,
        "segmentation": {"id": seg, "is_mock": seg == "mock"},
        "embedder": {"id": s.EMBEDDER},
    }


def _hash(req: VariationRequest) -> str:
    body = json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


# ---- create ----


def create_run(
    session: Session, board_id: str, req: VariationRequest, idempotency_key: str | None
) -> VariationRun:
    board = boards_repo.get(session, board_id)
    if board is None:
        raise AppError(404, "BOARD_NOT_FOUND", "Board not found")
    route = f"POST /api/boards/{board_id}/runs"
    digest = _hash(req)
    if idempotency_key:
        seen = idem_repo.get(session, idempotency_key)
        if seen is not None:
            if seen.route != route or seen.request_hash != digest:
                raise AppError(
                    409, "IDEMPOTENCY_KEY_REUSED",
                    "This Idempotency-Key was already used for a different request",
                )  # fmt: skip
            run = runs_repo.get(session, seen.response_json["run_id"])
            if run is not None:
                return run
    item = items_repo.get(session, req.source_item_id)
    if item is None or item.removed_at is not None or item.board_id != board_id:
        raise AppError(404, "ITEM_NOT_FOUND", "Source item not found on this board")
    lens_row = lenses_repo.get(session, board.lens_id) if board.lens_id else None
    if lens_row is None or lens_row.status != "confirmed":
        raise AppError(409, "LENS_REQUIRED", "Confirm this board's lens before varying an item")
    if not item.embedding_json:
        raise AppError(409, "SOURCE_NOT_READY", "The source item has not been analysed yet")
    lens = LensSpec.model_validate(lens_row.spec_json)
    records = source_records(session, item.id)
    validate_variation(req, item, records, lens)  # 422 before any row exists
    profile = profiles_repo.latest(session, board_id)
    run = runs_repo.create(
        session, board_id=board_id, source_item_id=item.id, lens_id=lens_row.id,
        target_key=req.target_key, mode=req.mode, target_values_json=list(req.target_values),
        nudge_json=req.nudge.model_dump() if req.nudge else None,
        protected_keys_json=list(req.protected_keys),
        source_snapshot_json=[r.model_dump(mode="json") for r in records],
        board_profile_version=profile.version if profile else 0,
        ranking_version=RANKING_CONFIG.version, ranking_config_json=RANKING_CONFIG.model_dump(),
        validator_version=VALIDATOR_VERSION, providers_json=_provider_snapshot(),
        status="queued", progress_json={"stage": "queued", "validated_n": 0, "shortlist_n": 0},
        idempotency_key=idempotency_key or f"auto_{hashlib.sha256(digest.encode()).hexdigest()[:8]}"
        f"_{datetime.now(UTC).timestamp()}",
    )  # fmt: skip
    if idempotency_key:
        idem_repo.put(session, idempotency_key, route, digest, 202, {"run_id": run.id})
    after_commit(session, partial(jobs.enqueue, JOB, run_id=run.id))
    return run


# ---- execute ----


def _progress(session: Session, run: VariationRun, stage: str, **extra: Any) -> None:
    prog = {**(run.progress_json or {}), "stage": stage, **extra}
    run.progress_json = prog
    session.flush()
    payload = {
        "run_id": run.id, "stage": stage, "validated_n": prog.get("validated_n", 0),
        "shortlist_n": prog.get("shortlist_n", 0),
    }  # fmt: skip
    after_commit(session, partial(events.publish, run.board_id, "run.progress", payload))


def _scores(c: Candidate) -> dict[str, float]:
    return {k: float(v) for k, v in asdict(c.scores).items()}


def _providers() -> Providers:
    s = get_settings()
    try:
        reasoning = get_reasoning(s)
    except ModelError:
        reasoning = None
    try:
        seg = get_segmentation(s)
    except ModelError:
        seg = None
    return Providers(reasoning, seg)


def _run(session: Session, run: VariationRun) -> None:
    cfg = RankingConfig.model_validate(run.ranking_config_json)
    board = boards_repo.get(session, run.board_id)
    item = items_repo.get(session, run.source_item_id)
    lens_row = lenses_repo.get(session, run.lens_id)
    assert board is not None and item is not None and lens_row is not None
    lens = LensSpec.model_validate(lens_row.spec_json)
    records = [AttributeRecord.model_validate(r) for r in run.source_snapshot_json]
    spec: VariationSpec = validate_variation(_request_of(run), item, records, lens)
    source_attrs = {r.key: AttrValue.from_record(r) for r in records}
    source = source_from_board_item(item, source_attrs)

    # retrieving
    run.status = "retrieving"
    _progress(session, run, "retrieving")
    session.commit()
    profile = profiles_repo.latest(session, board.id)
    centroid = (profile.profile_json or {}).get("centroid") if profile else None
    pool = build_pool(session, board, item.embedding_json, centroid, cfg)
    on_board = on_board_from_items(items_repo.list_active(session, board.id), item.id)
    kept, excluded = apply_exclusions(list(pool), spec, source, cfg, on_board)
    cands = [score_candidate(p, spec, source_attrs, cfg) for p in kept]
    rows: dict[str, Any] = {}
    for ex in excluded:
        p = ex["item"]
        rows[p.item.id] = runs_repo.add_candidate(
            session, run_id=run.id, corpus_item_id=p.item.id, state="excluded",
            excluded_reason=ex["reason"], excluded_detail=json.dumps(ex["detail"], default=str),
        )  # fmt: skip
    for c in cands:
        rows[c.pool.item.id] = runs_repo.add_candidate(
            session, run_id=run.id, corpus_item_id=c.pool.item.id, state="retrieved",
            scores_json=_scores(c),
        )  # fmt: skip
    top = shortlist(cands, cfg)
    for c in top:
        rows[c.pool.item.id].state = "validating"
        rows[c.pool.item.id].scores_json = _scores(c)
    run.status = "validating"
    _progress(
        session, run, "validating", validated_n=0, shortlist_n=len(top),
        invalid_unindexed=pool.meta.invalid_unindexed,
    )  # fmt: skip
    session.commit()

    # validating, a batch at a time
    providers = _providers()
    done: dict[str, CandidateValidation] = {}
    for i in range(0, len(top), MAX_CANDIDATES_PER_CALL):
        batch = top[i : i + MAX_CANDIDATES_PER_CALL]
        res = validate_shortlist(session, spec, source, batch, lens, cfg, providers)
        for c in batch:
            cid = c.pool.item.id
            v = res[cid]
            done[cid] = v
            row = rows[cid]
            row.state = v.overall
            row.observed_target_json = v.observed_target_value
            for ck in v.checks:
                runs_repo.add_validation(
                    session, run_candidate_id=row.id, check=ck.check,
                    attribute_key=ck.attribute_key, verdict=ck.verdict, reason=ck.reason,
                    evidence_json=ck.evidence, validator_version=run.validator_version,
                )  # fmt: skip
        _progress(session, run, "validating", validated_n=len(done))
        session.commit()

    # selecting
    ok = [c for c in top if done[c.pool.item.id].overall == "validated"]
    for c in select_diverse(ok, spec, cfg, cfg.result_size):
        row = rows[c.pool.item.id]
        row.rank = c.rank
        row.scores_json = _scores(c)
    session.flush()
    run.summary_json = summarize_run(session, run, lens)
    run.status = "completed"
    run.completed_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    _progress(session, run, "completed")
    session.commit()


def execute_run(session_factory: sessionmaker[Session], run_id: str) -> None:
    with session_factory() as session:
        run = runs_repo.get(session, run_id)
        if run is None or run.status != "queued":
            return
        board_id = run.board_id
        try:
            _run(session, run)
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError | ModelError) else "RUN_ERROR"
            if code == "RUN_ERROR":
                log.exception("run %s failed", run_id)
            session.rollback()
            run = runs_repo.get(session, run_id)
            if run is not None:
                run.status = "failed"
                run.error_code = str(code)
                _progress(session, run, "failed")
            else:  # pragma: no cover
                events.publish(board_id, "run.progress", {"run_id": run_id, "stage": "failed"})
            session.commit()


def run_variation_job(run_id: str) -> None:
    from app.api import deps

    execute_run(deps._factory(), run_id)


jobs.register(JOB, run_variation_job)


# ---- reads ----


def mark_stale(session: Session, run: VariationRun, now: datetime | None = None) -> bool:
    """A run still going after STALE_AFTER lost its worker: fail it as interrupted."""
    if run.status in TERMINAL:
        return False
    created = datetime.fromisoformat(run.created_at)
    if (now or datetime.now(UTC)) - created <= STALE_AFTER:
        return False
    run.status = "failed"
    run.error_code = "RUN_INTERRUPTED"
    _progress(session, run, "failed")
    session.commit()
    return True
