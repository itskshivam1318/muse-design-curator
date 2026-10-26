from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_error_handlers
from app.spa import spa_router


def make(dist: Path) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(spa_router(dist))
    return TestClient(app)


def test_serves_files_and_falls_back_to_index(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    c = make(tmp_path)
    assert c.get("/api/health").json() == {"ok": True}
    assert c.get("/assets/app.js").text == "console.log(1)"
    for path in ("/", "/boards/brd_123", "/assets/missing.js"):
        r = c.get(path)
        assert r.status_code == 200 and "id=root" in r.text, path
    assert "nope" not in c.get("/..%2Fsecret.txt").text
    r = c.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_missing_build_is_404(tmp_path: Path) -> None:
    r = make(tmp_path).get("/boards/x")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
