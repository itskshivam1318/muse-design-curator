from fastapi import FastAPI

from app.errors import register_error_handlers

app = FastAPI(title="Design Language Engine")
register_error_handlers(app)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}
