import csv
import io

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.db.models import Decision
from app.errors import AppError

router = APIRouter(prefix="/api")
CSV_COLUMNS = [
    "created_at", "run_id", "candidate_id", "corpus_item_id", "decision", "reason_code",
    "note", "item_id",
]  # fmt: skip


def _safe(v: str | None) -> str:
    """Neutralise spreadsheet formulas: prefix cells starting with = + - @ tab or CR."""
    text = v or ""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.post("/runs/{run_id}/candidates/{candidate_id}/decisions")
def post_decision(run_id: str, candidate_id: str) -> None:
    """Vary is retired: its candidates can no longer be kept or rejected."""
    raise AppError(410, "VARY_RETIRED", "Vary has been replaced by Explore")


@router.get("/boards/{board_id}/decisions.csv")
def decisions_csv(board_id: str, session: SessionDep) -> Response:
    require_board(session, board_id)
    q = select(Decision).where(Decision.board_id == board_id)
    rows = session.scalars(q.order_by(Decision.created_at.desc(), Decision.id.desc()))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for d in rows:
        w.writerow([
            _safe(c) for c in (
                d.created_at, d.run_id, d.run_candidate_id, d.corpus_item_id, d.decision,
                d.reason_code, d.note, d.item_id,
            )
        ])  # fmt: skip
    return Response(buf.getvalue(), media_type="text/csv")
