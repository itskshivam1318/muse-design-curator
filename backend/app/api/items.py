from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app import events, jobs
from app.api.boards import require_board
from app.api.deps import SessionDep
from app.api.schemas import ItemPatch, JsonIngest, item_to_dict
from app.db.models import BoardItem
from app.db.repos import items as items_repo
from app.db.session import after_commit
from app.errors import AppError
from app.extraction import service as extraction
from app.ingest.capture import ingest_capture_frames, ingest_capture_image
from app.ingest.common import GAP, IngestResult, ItemMeta
from app.ingest.images import ingest_image
from app.ingest.links import ingest_link
from app.ingest.sniff import sniff_image, sniff_video
from app.ingest.video import choose_frame, ingest_video

router = APIRouter(prefix="/api")
MAX_FILES = 50


def _ingest_file(session: Session, board_id: str, data: bytes, meta: ItemMeta) -> IngestResult:
    if sniff_image(data):
        return ingest_image(session, board_id, data, meta)
    if sniff_video(data):
        return ingest_video(session, board_id, data, meta)
    raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported file type")


def _announce(session: Session, results: list[IngestResult]) -> None:
    """After commit: emit item.added and enqueue parsing for new, non-link, non-failed items."""
    for r in results:
        if r.deduped:
            continue
        i = r.item
        events.publish(i.board_id, "item.added", item_to_dict(i))
        if i.kind != "link" and i.parse_status == "pending":
            jobs.enqueue("parse_item", item_id=i.id)


def _origin_for_upload(request: Request) -> str:
    return "drop" if request.query_params.get("origin") == "drop" else "upload"


async def _files_ingest(
    request: Request, session: Session, board_id: str, form: Any
) -> tuple[dict[str, Any], int, list[IngestResult]]:
    uploads = [
        f for k in ("files[]", "files") for f in form.getlist(k) if isinstance(f, UploadFile)
    ]
    if not 1 <= len(uploads) <= MAX_FILES:
        raise AppError(400, "VALIDATION_ERROR", f"Send 1-{MAX_FILES} files")
    x = _num(form.get("x"))
    y = _num(form.get("y"))
    origin = _origin_for_upload(request)
    payloads = [(u.filename or "", await u.read()) for u in uploads]

    def work() -> tuple[list[dict[str, Any]], list[IngestResult]]:
        out: list[dict[str, Any]] = []
        done: list[IngestResult] = []
        cursor = (x, y)
        for name, data in payloads:
            try:
                res = _ingest_file(
                    session, board_id, data,
                    ItemMeta(origin=origin, filename=name, x=cursor[0], y=cursor[1]),
                )  # fmt: skip
            except AppError as e:
                out.append(
                    {"filename": name, "ok": False,
                     "error": {"code": e.code, "message": e.message}}
                )  # fmt: skip
                continue
            done.append(res)
            out.append(
                {
                    "filename": name,
                    "ok": True,
                    "deduped": res.deduped,
                    "item": item_to_dict(res.item),
                }
            )
            if cursor[0] is not None and cursor[1] is not None and not res.deduped:
                cursor = (res.item.x + res.item.w + GAP, cursor[1])
        return out, done

    results, done = await run_in_threadpool(work)
    ok = any(r["ok"] for r in results)
    return {"results": results}, (200 if ok else 400), done


def _num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError) as e:
        raise AppError(400, "VALIDATION_ERROR", "x and y must be numbers") from e


def _json_ingest(session: Session, board_id: str, body: JsonIngest) -> IngestResult:
    if (body.url is None) == (body.capture is None):
        raise AppError(400, "VALIDATION_ERROR", "Provide exactly one of url or capture")
    if body.url is not None:
        return ingest_link(session, board_id, body.url, ItemMeta(origin="link", x=body.x, y=body.y))
    c = body.capture
    assert c is not None
    meta = ItemMeta(
        origin="extension", source_url=c.source_url, page_url=c.page_url,
        page_title=c.page_title, creator_handle=c.creator_handle, x=body.x, y=body.y,
    )  # fmt: skip
    if c.frames_b64:
        return ingest_capture_frames(session, board_id, c.frames_b64, meta)
    if c.image_b64:
        return ingest_capture_image(session, board_id, c.image_b64, meta)
    raise AppError(400, "VALIDATION_ERROR", "capture needs image_b64 or frames_b64")


@router.post("/boards/{board_id}/items")
async def add_items(board_id: str, request: Request, session: SessionDep) -> Any:
    from fastapi.responses import JSONResponse

    require_board(session, board_id)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        body, status, done = await _files_ingest(request, session, board_id, form)
    else:
        try:
            parsed = JsonIngest.model_validate(await request.json())
        except (ValidationError, ValueError) as e:
            raise AppError(400, "VALIDATION_ERROR", "Invalid request body") from e
        res = await run_in_threadpool(_json_ingest, session, board_id, parsed)
        done = [res]
        body, status = {"item": item_to_dict(res.item), "deduped": res.deduped}, 201
    after_commit(session, lambda: _announce(session, done))
    await run_in_threadpool(session.commit)
    return JSONResponse(body, status_code=status)


def _require_item(session: Session, item_id: str) -> BoardItem:
    item = items_repo.get(session, item_id)
    if item is None or item.removed_at is not None:
        raise AppError(404, "ITEM_NOT_FOUND", "Item not found")
    return item


@router.patch("/items/{item_id}")
def patch_item(item_id: str, body: ItemPatch, session: SessionDep) -> dict[str, Any]:
    item = _require_item(session, item_id)
    fields = body.model_dump(exclude_none=True)
    frame_id = fields.pop("chosen_frame_id", None)
    if frame_id is not None:
        choose_frame(session, item_id, frame_id)
        extraction.request_parse(session, item_id)
    if fields:
        items_repo.update(session, item_id, **fields)
    session.refresh(item)
    data = item_to_dict(item)
    events.publish(item.board_id, "item.updated", data)
    return data


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, session: SessionDep) -> None:
    item = _require_item(session, item_id)
    items_repo.soft_delete(session, item_id)
    events.publish(item.board_id, "item.removed", {"id": item_id})
