"""Draw a picture again from another viewpoint: a job that adds the result to the board."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.api.deps import SessionDep
from app.views import service

router = APIRouter(prefix="/api")


class RenderViewBody(BaseModel):
    view: str = Field(min_length=1, max_length=120)
    words: str | None = Field(None, max_length=200)

    @field_validator("view")
    @classmethod
    def _stripped(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("view must not be blank")
        return v


@router.post("/items/{anchor_id}/render-view", status_code=202)
def render_view(anchor_id: str, body: RenderViewBody, session: SessionDep) -> dict[str, Any]:
    return service.request_render_view(session, anchor_id, body.view, body.words)
