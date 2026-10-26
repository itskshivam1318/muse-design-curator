from typing import Annotated, Any

from fastapi import APIRouter, Body
from pydantic import ValidationError

from app import lens_service
from app.api.boards import require_board
from app.api.deps import SessionDep
from app.db.repos import lenses as lenses_repo
from app.domain.lens import LensSpec
from app.errors import AppError

router = APIRouter(prefix="/api")


@router.post("/boards/{board_id}/lens:propose")
def propose(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    return lens_service.lens_to_dict(lens_service.propose_lens_row(session, board_id))


@router.put("/boards/{board_id}/lens")
def put_lens(
    board_id: str, session: SessionDep, body: Annotated[dict[str, Any] | None, Body()] = None
) -> dict[str, Any]:
    require_board(session, board_id)
    spec: LensSpec | None = None
    if body:
        try:
            spec = LensSpec.model_validate(body)
        except ValidationError as exc:
            raise AppError(
                400, "VALIDATION_ERROR", "Lens validation failed",
                [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
            ) from exc  # fmt: skip
    return lens_service.lens_to_dict(lens_service.confirm_lens(session, board_id, spec))


@router.get("/lenses/{lens_id}")
def get_lens(lens_id: str, session: SessionDep) -> dict[str, Any]:
    row = lenses_repo.get(session, lens_id)
    if row is None:
        raise AppError(404, "LENS_NOT_FOUND", "Lens not found")
    return lens_service.lens_to_dict(row)
