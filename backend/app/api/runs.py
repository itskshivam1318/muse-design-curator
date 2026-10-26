from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.db.models import CorpusItem, RunCandidate, VariationRun
from app.db.repos import corpus as corpus_repo
from app.db.repos import decisions as decisions_repo
from app.db.repos import lenses as lenses_repo
from app.db.repos import runs as runs_repo
from app.domain.lens import LensSpec
from app.domain.variation import VariationRequest
from app.errors import AppError
from app.runs import orchestrator
from app.runs.summary import summarize_run
from app.storage import files

router = APIRouter(prefix="/api")
NEEDS_REVIEW_MAX = 6


@router.post("/boards/{board_id}/runs", status_code=202)
def create_run(
    board_id: str,
    body: VariationRequest,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    require_board(session, board_id)
    run = orchestrator.create_run(session, board_id, body, idempotency_key or None)
    return JSONResponse({"run_id": run.id}, status_code=202)


def image_url(corpus_id: str) -> str:
    return f"/api/corpus/{corpus_id}/image"


def _decision(d: Any) -> dict[str, Any]:
    return {
        "id": d.id, "decision": d.decision, "reason_code": d.reason_code, "note": d.note,
        "item_id": d.item_id, "created_at": d.created_at,
    }  # fmt: skip


def candidate_view(session: Session, cand: RunCandidate, cx: CorpusItem) -> dict[str, Any]:
    history = [_decision(d) for d in decisions_repo.history(session, cand.id)]
    return {
        "id": cand.id,
        "corpus_item_id": cx.id,
        "image_url": image_url(cx.id),
        "width": cx.width, "height": cx.height,
        "provenance": {
            "credit": cx.attribution_text, "landing_url": cx.landing_url,
            "license_code": cx.license_code, "creator_name": cx.creator_name,
        },
        "state": cand.state,
        "rank": cand.rank,
        "scores": cand.scores_json,
        "checks": [
            {"check": v.check, "attribute_key": v.attribute_key, "verdict": v.verdict,
             "reason": v.reason, "evidence": v.evidence_json}
            for v in runs_repo.validations(session, cand.id)
        ],
        "observed_target_value": cand.observed_target_json,
        "decision": history[0] if history else None,
        "decisions": history,
    }


def _total(c: RunCandidate) -> float:
    return float((c.scores_json or {}).get("total", 0.0))


def run_view(run: VariationRun) -> dict[str, Any]:
    return {
        "id": run.id, "board_id": run.board_id, "source_item_id": run.source_item_id,
        "lens_id": run.lens_id, "target_key": run.target_key, "mode": run.mode,
        "target_values": run.target_values_json, "nudge": run.nudge_json,
        "protected_keys": run.protected_keys_json, "status": run.status,
        "error_code": run.error_code, "ranking_version": run.ranking_version,
        "ranking_config": run.ranking_config_json, "validator_version": run.validator_version,
        "board_profile_version": run.board_profile_version, "providers": run.providers_json,
        "created_at": run.created_at, "completed_at": run.completed_at,
    }  # fmt: skip


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: SessionDep) -> dict[str, Any]:
    run = runs_repo.get(session, run_id)
    if run is None:
        raise AppError(404, "RUN_NOT_FOUND", "Run not found")
    orchestrator.mark_stale(session, run)
    cands = runs_repo.candidates(session, run_id)
    corpus = {c.corpus_item_id: corpus_repo.get(session, c.corpus_item_id) for c in cands}

    def view(c: RunCandidate) -> dict[str, Any]:
        return candidate_view(session, c, corpus[c.corpus_item_id])  # type: ignore[arg-type]

    results = [view(c) for c in cands if c.rank is not None]
    uncertain = sorted((c for c in cands if c.state == "uncertain"), key=lambda c: -_total(c))
    rejected = sorted((c for c in cands if c.state == "rejected"), key=lambda c: -_total(c))
    summary = run.summary_json
    if summary is None and run.status == "failed":
        lens_row = lenses_repo.get(session, run.lens_id)
        if lens_row is not None:
            summary = summarize_run(session, run, LensSpec.model_validate(lens_row.spec_json))
    return {
        "run": run_view(run),
        "progress": run.progress_json,
        "summary": summary,
        "results": results,
        "needs_review": [view(c) for c in uncertain[:NEEDS_REVIEW_MAX]],
        "rejected": [view(c) for c in rejected],
        "excluded_counts": (summary or {}).get("excluded", {}),
    }


@router.get("/corpus/{corpus_id}/image")
def corpus_image(corpus_id: str, session: SessionDep) -> FileResponse:
    cx = session.get(CorpusItem, corpus_id)
    if cx is None or not cx.local_path or not files.abs_path(cx.local_path).is_file():
        raise AppError(404, "IMAGE_NOT_FOUND", "Image not found")
    return FileResponse(files.abs_path(cx.local_path))
