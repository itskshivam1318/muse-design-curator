"""Board UI events: the frontend posts small batches; read back newest first for debugging."""

import json
from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.db.models import UiEvent

router = APIRouter(prefix="/api")

MAX_BATCH = 50
MAX_DETAIL_BYTES = 2000


class UiEventIn(BaseModel):
    action: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,47}$")
    item_id: str | None = Field(default=None, max_length=64)
    run_id: str | None = Field(default=None, max_length=64)
    detail: dict[str, Any] | None = None
    at: str | None = Field(default=None, max_length=40)

    @field_validator("detail")
    @classmethod
    def _small(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v, default=str)) > MAX_DETAIL_BYTES:
            raise ValueError(f"detail over {MAX_DETAIL_BYTES} bytes")
        return v


class UiEventBatch(BaseModel):
    events: list[UiEventIn] = Field(min_length=1, max_length=MAX_BATCH)


@router.post("/boards/{board_id}/ui-events", status_code=204)
def post_ui_events(board_id: str, body: UiEventBatch, session: SessionDep) -> Response:
    require_board(session, board_id)
    for e in body.events:
        session.add(UiEvent(
            board_id=board_id, action=e.action, item_id=e.item_id, run_id=e.run_id,
            detail_json=e.detail, client_at=e.at,
        ))  # fmt: skip
    return Response(status_code=204)


@router.get("/boards/{board_id}/ui-events")
def list_ui_events(
    board_id: str, session: SessionDep, limit: int = Query(200, ge=1, le=1000)
) -> list[dict[str, Any]]:
    require_board(session, board_id)
    q = (
        select(UiEvent).where(UiEvent.board_id == board_id)
        .order_by(UiEvent.id.desc()).limit(limit)
    )  # fmt: skip
    return [
        {"id": r.id, "action": r.action, "item_id": r.item_id, "run_id": r.run_id,
         "detail": r.detail_json, "at": r.client_at, "created_at": r.created_at}
        for r in session.scalars(q)
    ]  # fmt: skip
