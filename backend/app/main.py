from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import demo
from app.api import attributes, boards, decisions, extension, items, lenses, media, runs, ui_events
from app.api import demo as demo_api
from app.config import get_settings, resolve_repo_path
from app.errors import register_error_handlers
from app.extraction import service as _extraction  # noqa: F401  (registers the parse_item job)
from app.runs import orchestrator as _runs  # noqa: F401  (registers the run_variation job)
from app.spa import spa_router


def cors_origins() -> list[str]:
    settings = get_settings()
    origins = [settings.PUBLIC_APP_URL.rstrip("/")]
    if settings.EXTENSION_ORIGIN:
        origins.append(settings.EXTENSION_ORIGIN.rstrip("/"))
    return origins


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    demo.check_settings(get_settings())
    yield


app = FastAPI(title="Design Language Engine", lifespan=lifespan)


@app.middleware("http")
async def demo_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """DEMO_MODE: writes outside the open list need the unlock cookie (default deny)."""
    if (
        get_settings().DEMO_MODE
        and not demo.write_is_open(request.method, request.url.path)
        and not demo.is_unlocked(request)
    ):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "DEMO_LOCKED", "message": demo.LOCKED_MESSAGE}},
        )
    return await call_next(request)


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
app.include_router(ui_events.router)
app.include_router(demo_api.router)


@app.get("/api/health")
def health() -> dict[str, bool | str]:
    """`live` is false when model providers are mocked or the key they need is missing."""
    st = get_settings()
    uses_key = st.REASONING_PROVIDER.replace("_", "-") == "muse-spark" or (
        st.SEGMENTATION_PROVIDER.replace("_", "-") == "sam-3.1"
    )
    if uses_key and not st.MODEL_API_KEY:
        return {"ok": True, "live": False, "reason": "MODEL_API_KEY not set"}
    if st.REASONING_PROVIDER == "mock" and st.SEGMENTATION_PROVIDER == "mock":
        return {"ok": True, "live": False, "reason": "mock providers"}
    return {"ok": True, "live": True}


# Single-container deploy: the built frontend at /, registered last so /api routes win.
_dist = get_settings().FRONTEND_DIST
if _dist:
    app.include_router(spa_router(resolve_repo_path(_dist)))
