from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.api.schemas import item_to_dict
from app.notes.service import create_note

router = APIRouter(prefix="/api")


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    x: float
    y: float
    w: float | None = Field(default=None, gt=0)
    h: float | None = Field(default=None, gt=0)


@router.post("/boards/{board_id}/notes", status_code=201)
def add_note(board_id: str, body: NoteCreate, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    return item_to_dict(create_note(session, board_id, body.text, body.x, body.y, body.w, body.h))
