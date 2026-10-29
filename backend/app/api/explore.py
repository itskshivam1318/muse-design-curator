from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.config import get_settings
from app.db.models import ExploreOption
from app.db.repos import explore as explore_repo
from app.explore import keep, service, visualize

router = APIRouter(prefix="/api")


class ExploreBody(BaseModel):
    key: str
    steer: str | None = Field(None, max_length=200)
    parent_option_id: str | None = None
    mode: Literal["initial", "more", "further"] = "initial"


class OptionPatch(BaseModel):
    status: Literal["dismissed", "open"] | None = None
    x: float | None = None
    y: float | None = None


class VisualizeBody(BaseModel):
    """Where the browser drew the option's note; saved on the option before placing the image."""

    x: float
    y: float


class KeepBody(BaseModel):
    item_id: str
    x: float | None = None
    y: float | None = None


def _takes(session: SessionDep, opts: list[ExploreOption]) -> dict[str, list[str]]:
    return explore_repo.takes(session, [o.id for o in opts])


@router.post("/items/{item_id}/explore")
def explore_item(item_id: str, body: ExploreBody, session: SessionDep) -> dict[str, Any]:
    e, opts = service.explore(
        session, item_id, body.key, steer=body.steer, parent_option_id=body.parent_option_id,
        mode=body.mode,
    )  # fmt: skip
    return explore_repo.exploration_to_dict(e, opts, _takes(session, opts))


@router.get("/boards/{board_id}/explorations")
def board_explorations(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    if not get_settings().EXPLORE_ENABLED:
        return {"explorations": []}
    return {
        "explorations": [
            explore_repo.exploration_to_dict(e, opts, _takes(session, opts))
            for e, opts in explore_repo.for_board(session, board_id)
        ]
    }


@router.patch("/options/{option_id}")
def patch_option(option_id: str, body: OptionPatch, session: SessionDep) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    o = service.update_option(session, option_id, **fields)
    return explore_repo.option_to_dict(o, _takes(session, [o])[o.id])


@router.post("/options/{option_id}/visualize", status_code=202)
def visualize_option(
    option_id: str, session: SessionDep, body: VisualizeBody | None = None
) -> dict[str, Any]:
    at = (body.x, body.y) if body else None
    visualize.request_visualize(session, option_id, at=at)
    return {"option_id": option_id, "status": "visualizing"}


@router.post("/options/{option_id}/keep")
def keep_option(option_id: str, body: KeepBody, session: SessionDep) -> dict[str, Any]:
    at = (body.x, body.y) if body.x is not None and body.y is not None else None
    o = keep.keep_take(session, option_id, body.item_id, at)
    return explore_repo.option_to_dict(o, _takes(session, [o])[o.id])


@router.post("/options/{option_id}/unkeep")
def unkeep_option(option_id: str, session: SessionDep) -> dict[str, Any]:
    o = keep.unkeep(session, option_id)
    return explore_repo.option_to_dict(o, _takes(session, [o])[o.id])
