from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import AppError, register_error_handlers


def test_app_error_envelope() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise AppError(422, "X", "msg")

    @app.get("/boom2")
    def boom2() -> None:
        raise AppError(409, "Y", "m2", details={"a": 1})

    c = TestClient(app)
    r = c.get("/boom")
    assert r.status_code == 422
    assert r.json() == {"error": {"code": "X", "message": "msg"}}
    assert c.get("/boom2").json() == {"error": {"code": "Y", "message": "m2", "details": {"a": 1}}}


def test_handler_registered_on_main_app() -> None:
    from app.main import app

    assert AppError in app.exception_handlers
