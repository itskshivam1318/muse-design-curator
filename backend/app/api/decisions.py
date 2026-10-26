import csv
import io
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.db.models import Decision
from app.feedback.service import record_decision

router = APIRouter(prefix="/api")
CSV_COLUMNS = [
    "created_at", "run_id", "candidate_id", "corpus_item_id", "decision", "reason_code",
    "note", "item_id",
]  # fmt: skip


class DecisionBody(BaseModel):
    decision: str
    reason_code: str | None = None
    note: str | None = None
    mark_not_this: bool = False


@router.post("/runs/{run_id}/candidates/{candidate_id}/decisions", status_code=201)
def post_decision(
    run_id: str,
    candidate_id: str,
    body: DecisionBody,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    out = record_decision(
        session, run_id, candidate_id, body.decision, body.reason_code, body.note,
        body.mark_not_this, idempotency_key or None,
    )  # fmt: skip
    return JSONResponse(out, status_code=201)


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
            d.created_at, d.run_id, d.run_candidate_id, d.corpus_item_id, d.decision,
            d.reason_code or "", d.note or "", d.item_id or "",
        ])  # fmt: skip
    return Response(buf.getvalue(), media_type="text/csv")
