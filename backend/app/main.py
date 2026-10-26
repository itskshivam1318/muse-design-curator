from fastapi import FastAPI

from app.api import boards, items, lenses
from app.errors import register_error_handlers

app = FastAPI(title="Design Language Engine")
register_error_handlers(app)
app.include_router(boards.router)
app.include_router(items.router)
app.include_router(lenses.router)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}
