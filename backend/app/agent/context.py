"""What a tool runs with: an in-process client for the app's REST API, and the board/run it is on.

Tools never touch the database directly; they call the same `/api/...` routes the UI does, so
every guard (validation, demo lock, daily caps) applies to the agent too.
"""

from dataclasses import dataclass
from typing import Any, NamedTuple

import httpx


class ApiResult(NamedTuple):
    status: int
    body: Any


class ApiClient:
    """Calls the app over an ASGI transport (no network). Paths are full, e.g. `/api/boards`."""

    def __init__(self, app: Any = None) -> None:
        self._app = app
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            app = self._app
            if app is None:
                from app.main import app  # lazily: app.main imports the routers that use us

            self._client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://muse.internal"
            )
        return self._client

    async def _send(self, method: str, path: str, **kwargs: Any) -> ApiResult:
        response = await self._http().request(method, path, **kwargs)
        return ApiResult(response.status_code, _body(response))

    async def get(self, path: str) -> ApiResult:
        return await self._send("GET", path)

    async def post(self, path: str, json: Any = None, files: Any = None) -> ApiResult:
        return await self._send("POST", path, json=json, files=files)

    async def patch(self, path: str, json: Any) -> ApiResult:
        return await self._send("PATCH", path, json=json)

    async def delete(self, path: str) -> ApiResult:
        return await self._send("DELETE", path)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    if "json" in response.headers.get("content-type", ""):
        return response.json()
    return response.text


@dataclass
class ToolContext:
    api: ApiClient
    board_id: str | None
    run_id: str | None
    source: str


def api_error(status: int, body: Any) -> dict[str, Any]:
    """An API refusal as a tool error: `{"error": {"code", "message"}}` → `{"error", "message"}`."""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return {
            "error": str(err.get("code") or f"HTTP_{status}"),
            "message": str(err.get("message") or ""),
        }
    return {"error": f"HTTP_{status}", "message": str(body or "")[:200]}
