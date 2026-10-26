"""Serve the built frontend (FRONTEND_DIST) with an SPA fallback, for the one-container deploy."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.errors import AppError


def spa_router(dist: Path) -> APIRouter:
    root = dist.resolve()
    index = root / "index.html"
    router = APIRouter()

    @router.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise AppError(404, "NOT_FOUND", "Not Found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return FileResponse(candidate)
        if not index.is_file():
            raise AppError(404, "NOT_FOUND", "The frontend is not built")
        # the app's routes (/boards/<id>, ...) are client-side: always hand back the shell
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return router
