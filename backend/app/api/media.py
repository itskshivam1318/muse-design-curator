"""Item media: thumbnails, originals and video frames, looked up by id only (never by path)."""

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.db.models import BoardItem
from app.db.repos import items as items_repo
from app.errors import AppError
from app.storage import files

router = APIRouter(prefix="/api")
_CACHE = {"Cache-Control": "private, max-age=3600"}


def _not_found() -> AppError:
    return AppError(404, "IMAGE_NOT_FOUND", "Image not found")


def _active_item(session: Session, item_id: str) -> BoardItem:
    item = items_repo.get(session, item_id)
    if item is None or item.removed_at is not None:
        raise _not_found()
    return item


def _serve(rel: str | None) -> FileResponse:
    if not rel:
        raise _not_found()
    path: Path = files.abs_path(rel)
    if not path.is_file():
        raise _not_found()
    return FileResponse(path, headers=_CACHE)


def _chosen_frame_path(session: Session, item: BoardItem) -> str | None:
    frames = items_repo.frames(session, item.id)
    chosen = next((f for f in frames if f.chosen), frames[0] if frames else None)
    return chosen.storage_path if chosen else None


@router.get("/items/{item_id}/image")
def item_image(
    item_id: str, session: SessionDep, size: Literal["thumb", "full"] = "thumb"
) -> FileResponse:
    item = _active_item(session, item_id)
    if item.kind == "link":
        raise _not_found()
    if size == "thumb":
        return _serve(item.thumb_path)
    if item.kind == "video":  # the full view of a video is its chosen frame, not the video
        return _serve(_chosen_frame_path(session, item) or item.thumb_path)
    return _serve(item.storage_path)


@router.get("/items/{item_id}/frames")
def item_frames(item_id: str, session: SessionDep) -> dict[str, Any]:
    item = _active_item(session, item_id)
    return {
        "frames": [
            {"id": f.id, "t_ms": f.t_ms, "chosen": f.chosen}
            for f in items_repo.frames(session, item.id)
        ]
    }


@router.get("/items/{item_id}/frames/{frame_id}/image")
def frame_image(item_id: str, frame_id: str, session: SessionDep) -> FileResponse:
    item = _active_item(session, item_id)
    frame = next((f for f in items_repo.frames(session, item.id) if f.id == frame_id), None)
    if frame is None:
        raise _not_found()
    return _serve(frame.storage_path)
