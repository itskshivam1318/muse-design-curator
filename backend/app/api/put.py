"""Put one picture into chosen spots of another: a job that adds the result to the board."""

from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import SessionDep
from app.put import service

router = APIRouter(prefix="/api")

_Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class PointAt(BaseModel):
    fx: _Fraction
    fy: _Fraction


class PartSpot(BaseModel):
    part: str = Field(min_length=1)


class PointSpot(BaseModel):
    point: PointAt


class PutIntoBody(BaseModel):
    source_id: str
    spots: list[PartSpot | PointSpot] = Field(min_length=1, max_length=8)
    words: str | None = Field(None, max_length=200)


@router.post("/items/{target_id}/put-into", status_code=202)
def put_into(target_id: str, body: PutIntoBody, session: SessionDep) -> dict[str, Any]:
    spots = [s.model_dump() for s in body.spots]
    return service.request_put_into(session, target_id, body.source_id, spots, body.words)
