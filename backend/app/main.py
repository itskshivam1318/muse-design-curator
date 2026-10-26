from fastapi import FastAPI

app = FastAPI(title="Design Language Engine")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}
