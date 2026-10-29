from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import object_session

from app.db.models import Board, BoardItem, CorpusItem

ItemRole = Literal["reference", "counter_example"]


class BoardCreate(BaseModel):
    title: str = Field(min_length=1)
    context: str = ""
    domain: str | None = None


class BoardPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    context: str | None = None
    domain: str | None = None


class ItemPatch(BaseModel):
    x: float | None = None
    y: float | None = None
    w: float | None = Field(default=None, gt=0)
    h: float | None = Field(default=None, gt=0)
    z: int | None = None
    role: ItemRole | None = None
    chosen_frame_id: str | None = None


class Capture(BaseModel):
    image_b64: str | None = None
    frames_b64: list[str] | None = None
    source_url: str | None = None
    page_url: str | None = None
    page_title: str | None = None
    creator_handle: str | None = None
    kind: Literal["image", "video"] = "image"


class JsonIngest(BaseModel):
    url: str | None = None
    capture: Capture | None = None
    x: float | None = None
    y: float | None = None


def board_to_dict(b: Board) -> dict[str, Any]:
    return {
        "id": b.id, "title": b.title, "context": b.context, "domain": b.domain,
        "lens_id": b.lens_id, "created_at": b.created_at, "updated_at": b.updated_at,
    }  # fmt: skip


def licence_of(i: BoardItem) -> dict[str, Any] | None:
    """The stored credit for a licensed (corpus) image; never invented. None for user items."""
    if i.corpus_item_id is None:
        return None
    session = object_session(i)
    cx = session.get(CorpusItem, i.corpus_item_id) if session is not None else None
    if cx is None:
        return None
    return {
        "credit": cx.attribution_text, "license_code": cx.license_code,
        "license_url": cx.license_url, "creator_name": cx.creator_name,
        "landing_url": cx.landing_url, "source": cx.source,
    }  # fmt: skip


def item_to_dict(i: BoardItem) -> dict[str, Any]:
    return {
        "id": i.id, "board_id": i.board_id, "kind": i.kind, "origin": i.origin,
        "sha256": i.sha256, "mime": i.mime, "width": i.width, "height": i.height,
        "original_filename": i.original_filename, "source_url": i.source_url,
        "page_url": i.page_url, "page_title": i.page_title,
        "creator_handle": i.creator_handle, "captured_at": i.captured_at,
        "rights_status": i.rights_status, "parse_status": i.parse_status,
        "parse_error_code": i.parse_error_code, "role": i.role,
        "x": i.x, "y": i.y, "w": i.w, "h": i.h, "z": i.z,
        "storage_path": i.storage_path, "thumb_path": i.thumb_path,
        "parent_item_id": i.parent_item_id, "created_at": i.created_at,
        "licence": licence_of(i), "explore_option_id": i.explore_option_id,
        "generation": i.generation_json, "check": i.check_json,
        "note_text": i.note_text, "staged": bool(i.staged),
    }  # fmt: skip
