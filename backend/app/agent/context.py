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

    async def post(
        self, path: str, json: Any = None, files: Any = None, data: Any = None
    ) -> ApiResult:
        return await self._send("POST", path, json=json, files=files, data=data)

    async def put(self, path: str, json: Any = None) -> ApiResult:
        return await self._send("PUT", path, json=json)

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


SLOT_GAP = 40
SLOT_ROW = 4


def next_slot(items: list[dict[str, Any]]) -> tuple[float, float]:
    """Where the next item goes by default: right of everything on the board, 40 px clear.

    Items placed this way form a row; a row holds 4 items, then the next starts below it,
    under the row's first item. Items carry `x`, `y`, `w`, `h`.
    """
    if not items:
        return 0.0, 0.0
    lead = max(items, key=lambda i: (i["x"] + i["w"], -i["y"]))
    row = [i for i in items if i["y"] == lead["y"]]
    left = min(i["x"] for i in row)
    below = [i for i in items if i["y"] > lead["y"] and i["x"] >= left]
    if below:  # rows already started under the first: the newest is the lowest
        row = [i for i in below if i["y"] == max(b["y"] for b in below)]
    if len(row) >= SLOT_ROW:
        return float(left), float(max(i["y"] + i["h"] for i in row) + SLOT_GAP)
    return float(max(i["x"] + i["w"] for i in row) + SLOT_GAP), float(row[0]["y"])


async def board_items(ctx: ToolContext) -> list[dict[str, Any]] | dict[str, Any]:
    """The open board's items, or a tool error."""
    status, body = await ctx.api.get(f"/api/boards/{ctx.board_id}/items")
    return body["items"] if status == 200 else api_error(status, body)


async def place(ctx: ToolContext, args: dict[str, Any]) -> tuple[float, float] | dict[str, Any]:
    """`(x, y)` from the args, or the next free slot when either is omitted."""
    if args.get("x") is not None and args.get("y") is not None:
        return float(args["x"]), float(args["y"])
    items = await board_items(ctx)
    return next_slot(items) if isinstance(items, list) else items


async def require_item(ctx: ToolContext, item_id: str) -> dict[str, Any]:
    """The item if it is live on the open board, else an `ITEM_NOT_ON_BOARD` error."""
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    for item in items:
        if item["id"] == item_id:
            return item
    return {"error": "ITEM_NOT_ON_BOARD", "message": f"{item_id} is not on the open board."}


async def require_option(ctx: ToolContext, option_id: str) -> dict[str, Any]:
    """The explore option if its exploration is of an item on the open board, else an
    `OPTION_NOT_ON_BOARD` error."""
    status, body = await ctx.api.get(f"/api/boards/{ctx.board_id}/explorations")
    if status != 200:
        return api_error(status, body)
    for exploration in body["explorations"]:
        for option in exploration["options"]:
            if option["id"] == option_id:
                return option  # type: ignore[no-any-return]
    return {"error": "OPTION_NOT_ON_BOARD", "message": f"{option_id} is not on the open board."}


def api_error(status: int, body: Any) -> dict[str, Any]:
    """An API refusal as a tool error: `{"error": {"code", "message"}}` → `{"error", "message"}`."""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return {
            "error": str(err.get("code") or f"HTTP_{status}"),
            "message": str(err.get("message") or ""),
        }
    return {"error": f"HTTP_{status}", "message": str(body or "")[:200]}
