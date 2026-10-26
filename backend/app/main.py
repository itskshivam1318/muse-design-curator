from fastapi import FastAPI

from app.api import attributes, boards, decisions, items, lenses, runs
from app.errors import register_error_handlers
from app.extraction import service as _extraction  # noqa: F401  (registers the parse_item job)
from app.runs import orchestrator as _runs  # noqa: F401  (registers the run_variation job)

app = FastAPI(title="Design Language Engine")
register_error_handlers(app)
app.include_router(boards.router)
app.include_router(items.router)
app.include_router(lenses.router)
app.include_router(attributes.router)
app.include_router(runs.router)
app.include_router(decisions.router)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}
