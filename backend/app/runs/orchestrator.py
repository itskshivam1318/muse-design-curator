"""Variation runs: create (validate + snapshot), then retrieve, validate and select in the background.

Each stage commits so polling sees progress; progress events go out after the commit.
"""

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

from app import events, jobs, lens_service
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
from app.live import queries as live_queries
from app.live import search as live_search
from app.live.quick_index import DEEPEN_JOB, MAX_DEEPEN_PER_RUN, quick_index
from app.providers import get_reasoning, get_segmentation
from app.providers.reliability import ModelError
from app.retrieval.config import RANKING_CONFIG, RankingConfig
from app.retrieval.filters import apply_exclusions, on_board_from_items, source_from_board_item
from app.retrieval.pool import Pool, build_pool, live_pool_items
from app.retrieval.scores import Candidate, score_candidate
from app.retrieval.select import select_diverse, shortlist
from app.runs.summary import summarize_run
from app.validation.comparators import AttrValue
from app.validation.validator import (
    VALIDATOR_VERSION,
    CandidateValidation,
    Providers,
    validate_shortlist,
)

log = logging.getLogger(__name__)

QUERY_TIMEOUT_S = 10.0  # the live query-writing call; fallback queries after that
LIVE_EXTRA_S = 20.0  # downloads and indexing get this much beyond LIVE_TIMEOUT_S
STALE_AFTER = timedelta(minutes=5)  # a started run with no heartbeat for this long lost its worker
QUEUED_STALE_AFTER = timedelta(minutes=15)  # a run that never started (counted from created_at)
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
    session: Session,
    board_id: str,
    req: VariationRequest,
    idempotency_key: str | None,
    client_ip: str | None = None,
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
    if item is None or item.removed_at is not None or item.staged or item.board_id != board_id:
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
        client_ip=client_ip,
        idempotency_key=idempotency_key or f"auto_{hashlib.sha256(digest.encode()).hexdigest()[:8]}"
        f"_{datetime.now(UTC).timestamp()}",
    )  # fmt: skip
    if idempotency_key:
        idem_repo.put(session, idempotency_key, route, digest, 202, {"run_id": run.id})
    after_commit(session, partial(jobs.enqueue, JOB, run_id=run.id))
    if lens_row.origin == "curated" and lens_service.needs_part_check(lens):
        # an older board's curated lens was never pruned on its images: do it in the background
        # (this run uses the lens as it is)
        after_commit(session, partial(jobs.enqueue, lens_service.PRUNE_JOB, board_id=board_id))
    return run


# ---- execute ----


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class RunInterrupted(Exception):
    """The run was marked failed elsewhere (stale); the worker must not overwrite that."""


def _advance(session: Session, run: VariationRun, status: str, **values: Any) -> None:
    """Move the run to `status` only while it is not terminal (a conditional UPDATE), so a run
    already failed as interrupted is never revived. Raises RunInterrupted otherwise."""
    session.flush()
    res = session.execute(
        update(VariationRun)
        .where(VariationRun.id == run.id, VariationRun.status.not_in(TERMINAL))
        .values(status=status, updated_at=_now_iso(), **values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise RunInterrupted(run.id)
    set_committed_value(run, "status", status)
    for k, v in values.items():
        set_committed_value(run, k, v)


def _progress(session: Session, run: VariationRun, stage: str, **extra: Any) -> None:
    prog = {**(run.progress_json or {}), "stage": stage, **extra}
    run.progress_json = prog
    run.updated_at = _now_iso()  # the heartbeat stale detection reads
    session.flush()
    payload = {
        "run_id": run.id, "stage": stage, "validated_n": prog.get("validated_n", 0),
        "shortlist_n": prog.get("shortlist_n", 0),
    }  # fmt: skip
    if "live" in prog:
        payload["live"] = prog["live"]
    after_commit(session, partial(events.publish, run.board_id, "run.progress", payload))


def _report(session: Session, run: VariationRun, stage: str, **extra: Any) -> None:
    """A progress-only update, best-effort. Pending work is committed first and that must not be
    lost; the progress write itself may lose a lock race, which is logged and never fails a run.
    """
    session.commit()
    run_id = run.id
    try:
        _progress(session, run, stage, **extra)
        session.commit()
    except OperationalError as exc:
        session.rollback()
        log.warning("run %s: %s progress update skipped (%s)", run_id, stage, exc.orig or exc)


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


def _live_enabled(board: Any) -> list[str]:
    """The live sources to search for this board, or [] when live search is off."""
    s = get_settings()
    if not s.LIVE_SEARCH or not board.domain:
        return []
    return live_search.configured(live_search.parse_sources(s.LIVE_SOURCES))


def _live_queries(
    session: Session, spec: VariationSpec, source_attrs: dict[str, AttrValue], lens: LensSpec,
    board: Any, providers: Providers,
) -> list[str]:  # fmt: skip
    if providers.reasoning is not None:
        try:
            written = live_queries.write_queries(
                spec, source_attrs, lens, board.context or "", providers.reasoning, session=session,
                timeout=QUERY_TIMEOUT_S,
            )  # fmt: skip
            return live_queries.with_broad(written, spec, lens)
        except Exception as exc:  # noqa: BLE001 - live search never fails the run
            log.warning("live query writing failed (%s); using fallback queries", exc)
    fallback = live_queries.fallback_queries(spec, lens)[: get_settings().LIVE_QUERY_COUNT]
    return live_queries.with_broad(fallback, spec, lens)


def _live_info(found: live_search.LiveItems, queries: list[str], indexed: int) -> dict[str, Any]:
    return {
        "queries": queries, "found": len(found), "indexed": indexed,
        "sources": {n: st.status for n, st in found.sources.items()},
        "failed": found.failed() + [
            {"source": st.name, "error_code": "TIMEOUT"}
            for st in found.sources.values() if st.status == "timeout"
        ],
    }  # fmt: skip


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

    # searching: the corpus pool and the live licensed-source search run side by side
    settings = get_settings()
    providers = _providers()
    live_sources = _live_enabled(board)
    domain = board.domain or ""
    _advance(session, run, "retrieving")
    session.commit()
    if live_sources:
        _report(
            session, run, "searching",
            live={"sources": {}, "searching": live_sources, "found": 0, "queries": []},
        )  # fmt: skip
    else:
        _report(session, run, "retrieving")
    profile = profiles_repo.latest(session, board.id)
    centroid = (profile.profile_json or {}).get("centroid") if profile else None
    live_ids: set[str] = set()
    live_fut = None
    live_queries_used: list[str] = []
    live_pool: ThreadPoolExecutor | None = None
    live_start = time.monotonic()
    live_deadline = live_start + settings.LIVE_TIMEOUT_S + LIVE_EXTRA_S
    if live_sources:
        live_queries_used = _live_queries(session, spec, source_attrs, lens, board, providers)
        known = live_search.known_in_corpus(session)
        session.commit()  # release the read/cache write before the threads start
        live_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-search")
        live_fut = live_pool.submit(
            live_search.search_live, live_queries_used, domain, live_sources,
            settings.LIVE_PER_SOURCE_LIMIT,
            max(1.0, min(settings.LIVE_TIMEOUT_S, live_deadline - time.monotonic() - LIVE_EXTRA_S)),
            known=known,
            max_candidates=settings.LIVE_MAX_CANDIDATES,
        )  # fmt: skip
    pool = build_pool(session, board, item.embedding_json, centroid, cfg)
    if live_fut is not None and live_pool is not None:
        live_extra: list[Any] = []
        try:
            found = live_fut.result(timeout=max(1.0, live_deadline - time.monotonic()))
            names_now = {n: st.status for n, st in found.sources.items()}
            _report(
                session, run, "searching",
                live={"sources": names_now, "found": len(found), "downloaded": 0,
                      "queries": live_queries_used},
            )  # fmt: skip

            def landed(n: int) -> None:
                _report(
                    session, run, "searching",
                    live={"sources": names_now, "found": len(found), "downloaded": n,
                          "queries": live_queries_used},
                )  # fmt: skip

            qreport: dict[str, int] = {}
            new_rows = (
                quick_index(
                    session, list(found), domain, deadline=live_deadline, on_download=landed,
                    report=qreport,
                )
                if found else []
            )  # fmt: skip
            live_ids = {r.id for r in new_rows}
            live_extra = live_pool_items(session, new_rows, item.embedding_json, centroid, cfg)
            info = _live_info(found, live_queries_used, len(new_rows))
            info["downloaded"] = len(new_rows)
            info["dropped"] = qreport.get("dropped", 0)
        except Exception as exc:  # noqa: BLE001 - the corpus alone still answers the run
            log.warning("live search failed: %s", exc)
            session.rollback()
            info = {
                "queries": live_queries_used, "found": 0, "indexed": 0, "sources": {},
                "failed": [], "error": type(exc).__name__,
            }  # fmt: skip
        finally:
            live_pool.shutdown(wait=False, cancel_futures=True)
        have = {p.item.id for p in pool}
        merged = list(pool) + [p for p in live_extra if p.item.id not in have]
        merged.sort(key=lambda p: (-p.relevance, p.item.id))
        pool = Pool(merged, pool.meta)
        run = runs_repo.get(session, run.id) or run
        _progress(session, run, "searching", live=info)
        session.commit()
    on_board = on_board_from_items(
        items_repo.list_active(session, board.id, include_staged=False), item.id
    )
    kept, excluded = apply_exclusions(list(pool), spec, source, cfg, on_board)
    cands = [score_candidate(p, spec, source_attrs, cfg) for p in kept]
    rows: dict[str, Any] = {}
    for ex in excluded:
        p = ex["item"]
        rows[p.item.id] = runs_repo.add_candidate(
            session, run_id=run.id, corpus_item_id=p.item.id, state="excluded",
            excluded_reason=ex["reason"], excluded_detail=json.dumps(ex["detail"], default=str),
            origin="live" if p.item.id in live_ids else None,
        )  # fmt: skip
    for c in cands:
        rows[c.pool.item.id] = runs_repo.add_candidate(
            session, run_id=run.id, corpus_item_id=c.pool.item.id, state="retrieved",
            scores_json=_scores(c), origin="live" if c.pool.item.id in live_ids else None,
        )  # fmt: skip
    top = shortlist(cands, cfg)
    for c in top:
        rows[c.pool.item.id].state = "validating"
        rows[c.pool.item.id].scores_json = _scores(c)
    _advance(session, run, "validating")
    _progress(
        session, run, "validating", validated_n=0, shortlist_n=len(top),
        invalid_unindexed=pool.meta.invalid_unindexed,
    )  # fmt: skip
    session.commit()

    # validating: the whole shortlist in one pass (verify batches and SAM calls run concurrently;
    # source crops are made once); progress is reported as verify batches finish
    done: dict[str, CandidateValidation] = validate_shortlist(
        session, spec, source, top, lens, cfg, providers,
        on_progress=lambda n: _report(session, run, "validating", validated_n=n),
    )  # fmt: skip
    for c in top:
        cid = c.pool.item.id
        v = done[cid]
        row = rows[cid]
        row.state = v.overall
        row.observed_target_json = v.observed_target_value
        for ck in v.checks:
            runs_repo.add_validation(
                session, run_candidate_id=row.id, check=ck.check,
                attribute_key=ck.attribute_key, verdict=ck.verdict, reason=ck.reason,
                evidence_json=ck.evidence, validator_version=run.validator_version,
            )  # fmt: skip
    _report(session, run, "validating", validated_n=len(done))

    # selecting
    ok = [c for c in top if done[c.pool.item.id].overall == "validated"]
    for c in select_diverse(ok, spec, cfg, cfg.result_size):
        row = rows[c.pool.item.id]
        row.rank = c.rank
        row.scores_json = _scores(c)
    session.flush()
    if not settings.DEMO_MODE or settings.DEMO_DEEPEN:  # no paid background work for visitors
        for c in [c for c in top if c.pool.item.id in live_ids][:MAX_DEEPEN_PER_RUN]:
            after_commit(
                session, partial(jobs.enqueue, DEEPEN_JOB, corpus_item_id=c.pool.item.id)
            )
    run.summary_json = summarize_run(session, run, lens)
    _advance(session, run, "completed", completed_at=_now_iso())
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
        except RunInterrupted:
            session.rollback()
            log.warning("run %s was marked interrupted while running; result dropped", run_id)
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError | ModelError) else "RUN_ERROR"
            if code == "RUN_ERROR":
                log.exception("run %s failed", run_id)
            session.rollback()
            run = runs_repo.get(session, run_id)
            if run is not None and run.status in TERMINAL:
                return  # already failed as interrupted: keep that verdict
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


def _is_stale(run: VariationRun, now: datetime) -> bool:
    if run.status in TERMINAL:
        return False
    if run.updated_at:  # started: judged by its heartbeat
        return now - datetime.fromisoformat(run.updated_at) > STALE_AFTER
    # never started: waiting for a worker (or lost from the in-process queue by a restart)
    return now - datetime.fromisoformat(run.created_at) > QUEUED_STALE_AFTER


def mark_stale(session: Session, run: VariationRun, now: datetime | None = None) -> bool:
    """Fail a run whose worker went quiet (no heartbeat for STALE_AFTER, or never started within
    QUEUED_STALE_AFTER) as RUN_INTERRUPTED, and refund the demo visitor it was charged to."""
    if not _is_stale(run, now or datetime.now(UTC)):
        return False
    try:
        _advance(session, run, "failed", error_code="RUN_INTERRUPTED")
    except RunInterrupted:  # it finished (or failed) meanwhile
        session.rollback()
        session.refresh(run)
        return False
    _progress(session, run, "failed")
    session.commit()
    if run.client_ip:
        from app import demo

        demo.refund_run(run.client_ip)
    return True
