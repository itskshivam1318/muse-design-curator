from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app import demo
from app.config import get_settings
from app.errors import AppError

router = APIRouter(prefix="/api/demo")


class UnlockBody(BaseModel):
    passcode: str = Field(max_length=200)


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    settings = get_settings()
    return {
        "demo_mode": settings.DEMO_MODE,
        "unlocked": demo.is_unlocked(request, settings),
        "explore_enabled": settings.EXPLORE_ENABLED,
    }


@router.post("/unlock")
def unlock(body: UnlockBody, request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()
    if not settings.DEMO_MODE:
        raise AppError(400, "DEMO_MODE_OFF", "This instance is not a demo; nothing to unlock")
    ip = demo.client_ip(request, settings)
    demo.check_unlock_attempts(ip)
    if not demo.passcode_matches(body.passcode, settings.DEMO_PASSCODE or ""):
        demo.record_unlock_failure(ip)
        raise AppError(401, "DEMO_PASSCODE_INVALID", "That passcode is not right.")
    expiry = int(demo.now()) + demo.COOKIE_TTL_S
    response.set_cookie(
        demo.COOKIE, demo.make_cookie(settings.DEMO_SECRET or "", expiry),
        max_age=demo.COOKIE_TTL_S, httponly=True, samesite="lax",
        secure=demo.is_https(request, settings), path="/",
    )  # fmt: skip
    return {"demo_mode": True, "unlocked": True, "expires_at": expiry}
