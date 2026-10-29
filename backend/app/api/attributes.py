from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.db.repos import attributes as attrs_repo
from app.errors import AppError
from app.extraction import service

router = APIRouter(prefix="/api")


class AttributePatch(BaseModel):
    value: str | float | bool | None = None
    action: Literal["confirm", "disable", "enable"] | None = None


@router.get("/items/{item_id}/attributes")
def get_attributes(item_id: str, session: SessionDep) -> dict[str, Any]:
    item = service._require_item(session, item_id)
    lens = service.current_lens(session, item.board_id)
    rows = attrs_repo.for_item(session, item_id)
    if lens is not None:
        order = {a.key: n for n, a in enumerate(lens.attributes)}
        extra = [r for r in rows if r.key not in order and r.source == "plugin"]
        rows = sorted((r for r in rows if r.key in order), key=lambda r: order[r.key]) + extra
    return {
        "parse_status": item.parse_status,
        "parse_error_code": item.parse_error_code,
        "lens": lens.model_dump(mode="json") if lens else None,
        "provider": service.provider_info(),
        "attributes": [service.attribute_to_dict(r) for r in rows],
    }


@router.patch("/items/{item_id}/attributes/{key}")
def patch_attribute(
    item_id: str, key: str, body: AttributePatch, session: SessionDep
) -> dict[str, Any]:
    value = body.value if "value" in body.model_fields_set else service._UNSET
    row = service.edit_attribute(session, item_id, key, value=value, action=body.action)
    return service.attribute_to_dict(row)


@router.get("/items/{item_id}/attributes/{key}/history")
def attribute_history(item_id: str, key: str, session: SessionDep) -> dict[str, Any]:
    service._require_item(session, item_id)
    return {
        "events": [
            {
                "id": e.id, "key": e.key, "actor": e.actor, "action": e.action,
                "before": e.before_json, "after": e.after_json, "created_at": e.created_at,
            }
            for e in attrs_repo.events(session, item_id, key)
        ]
    }  # fmt: skip


@router.post("/items/{item_id}/parse")
def retry_parse(item_id: str, session: SessionDep) -> JSONResponse:
    service._require_item(session, item_id)
    if not service.request_parse(session, item_id):
        raise AppError(409, "PARSE_IN_PROGRESS", "This item is already being parsed")
    session.commit()
    return JSONResponse({"parse_status": "pending"}, status_code=202)
