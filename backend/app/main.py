from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import attributes, boards, decisions, extension, items, lenses, media, runs
from app.config import get_settings
from app.errors import register_error_handlers
from app.extraction import service as _extraction  # noqa: F401  (registers the parse_item job)
from app.runs import orchestrator as _runs  # noqa: F401  (registers the run_variation job)


def cors_origins() -> list[str]:
    settings = get_settings()
    origins = [settings.PUBLIC_APP_URL.rstrip("/")]
    if settings.EXTENSION_ORIGIN:
        origins.append(settings.EXTENSION_ORIGIN.rstrip("/"))
    return origins


app = FastAPI(title="Design Language Engine")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(boards.router)
app.include_router(extension.router)
app.include_router(items.router)
app.include_router(media.router)
app.include_router(lenses.router)
app.include_router(attributes.router)
app.include_router(runs.router)
app.include_router(decisions.router)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}
