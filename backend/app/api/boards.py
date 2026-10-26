from typing import Any

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.schemas import BoardCreate, BoardPatch, board_to_dict, item_to_dict
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.errors import AppError

router = APIRouter(prefix="/api/boards")


def require_board(session: Session, board_id: str):  # type: ignore[no-untyped-def]
    board = boards_repo.get(session, board_id)
    if board is None:
        raise AppError(404, "BOARD_NOT_FOUND", "Board not found")
    return board


@router.post("", status_code=201)
def create_board(body: BoardCreate, session: SessionDep) -> dict[str, Any]:
    return board_to_dict(
        boards_repo.create(session, body.title, context=body.context, domain=body.domain)
    )


@router.get("/{board_id}")
def get_board(board_id: str, session: SessionDep) -> dict[str, Any]:
    return board_to_dict(require_board(session, board_id))


@router.patch("/{board_id}")
def patch_board(board_id: str, body: BoardPatch, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if "domain" in body.model_fields_set:
        fields["domain"] = body.domain
    board = boards_repo.update(session, board_id, **fields)
    assert board is not None
    return board_to_dict(board)


@router.get("/{board_id}/items")
def list_items(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    return {"items": [item_to_dict(i) for i in items_repo.list_active(session, board_id)]}
