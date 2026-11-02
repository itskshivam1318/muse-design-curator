"""Routes for the analysis loop: read what Muse sees in an item, correct it, cut parts out."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.analysis import context, extract, label, locate, service
from app.analysis.api_schemas import (
    AnalysisView,
    DimensionCreate,
    DimensionPatch,
    DimensionView,
    OfferBody,
    PartCreate,
    PartPatch,
    PartView,
    analysis_view,
    context_view,
    dimension_view,
    part_view,
)
from app.analysis.types import Region
from app.api.boards import require_board
from app.api.deps import SessionDep
from app.api.schemas import item_to_dict
from app.db.models import BoardItem, ItemAttribute
from app.db.repos import attributes as attrs_repo
from app.errors import AppError
from app.extraction.service import _require_item
from app.render.registry import renderers_for

router = APIRouter(prefix="/api")
# Writes here are guarded by the demo middleware (default deny); nothing is open while locked.


def _live_dimension(session: SessionDep, item: BoardItem, key: str) -> ItemAttribute:
    row = next((r for r in attrs_repo.for_item(session, item.id) if r.key == key), None)
    if row is None or row.removed:
        raise AppError(404, "UNKNOWN_ATTRIBUTE", f"{key!r} is not a dimension of this item")
    return row


@router.get("/items/{item_id}/analysis")
def get_analysis(item_id: str, session: SessionDep) -> AnalysisView:
    return analysis_view(session, _require_item(session, item_id))


@router.post("/items/{item_id}/analyse", status_code=202)
def analyse_item(item_id: str, session: SessionDep) -> JSONResponse:
    _require_item(session, item_id)
    if not service.queue_analyse(session, item_id):  # counts against the board's daily limit
        raise AppError(409, "PARSE_IN_PROGRESS", "This item is already being analysed")
    session.commit()
    return JSONResponse({"parse_status": "pending"}, status_code=202)


@router.get("/items/{item_id}/parts/{key}/region")
def get_region(item_id: str, key: str, session: SessionDep) -> Region:
    return locate.locate(session, item_id, key)


@router.post("/items/{item_id}/parts", status_code=201)
def add_part(item_id: str, body: PartCreate, session: SessionDep) -> PartView:
    return part_view(label.add_part(session, item_id, body.label, body.region))


@router.patch("/items/{item_id}/parts/{key}")
def rename_part(item_id: str, key: str, body: PartPatch, session: SessionDep) -> PartView:
    return part_view(label.rename_part(session, item_id, key, body.label))


@router.delete("/items/{item_id}/parts/{key}", status_code=204)
def remove_part(item_id: str, key: str, session: SessionDep) -> None:
    label.remove_part(session, item_id, key)


@router.post("/items/{item_id}/parts/{key}/extract")
def extract_part(item_id: str, key: str, session: SessionDep) -> dict[str, Any]:
    return item_to_dict(extract.extract(session, item_id, key))


@router.post("/items/{item_id}/dimensions", status_code=201)
def add_dimension(item_id: str, body: DimensionCreate, session: SessionDep) -> DimensionView:
    row = label.add_dimension(
        session, item_id, body.label, body.type, body.part, body.prompt, body.kind
    )
    return dimension_view(row)


@router.patch("/items/{item_id}/dimensions/{key}")
def update_dimension(
    item_id: str, key: str, body: DimensionPatch, session: SessionDep
) -> DimensionView:
    row = label.update_dimension(
        session, item_id, key, label=body.label, type=body.type, part=body.part,
        prompt=body.prompt,
    )  # fmt: skip
    return dimension_view(row)


@router.delete("/items/{item_id}/dimensions/{key}", status_code=204)
def remove_dimension(item_id: str, key: str, session: SessionDep) -> None:
    label.remove_dimension(session, item_id, key)


@router.get("/items/{item_id}/dimensions/{key}/renderers")
def get_renderers(item_id: str, key: str, session: SessionDep) -> list[dict[str, Any]]:
    item = _require_item(session, item_id)
    row = _live_dimension(session, item, key)
    return [asdict(r) for r in renderers_for(session, item, row)]


@router.get("/boards/{board_id}/context")
def board_context(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    return context_view(session, board_id)


@router.post("/boards/{board_id}/offers/accept")
def accept_offer(board_id: str, body: OfferBody, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    context.accept_offer(session, board_id, body.label, body.dim_type, body.kind, body.part)
    return context_view(session, board_id)


@router.post("/boards/{board_id}/offers/decline")
def decline_offer(board_id: str, body: OfferBody, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    context.decline_offer(session, board_id, body.label, body.dim_type, body.kind, body.part)
    return context_view(session, board_id)


__all__ = ["router"]
