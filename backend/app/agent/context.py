"""What a tool runs with: an in-process client for the app's REST API, and the board/run it is on.

Tools never touch the database directly; they call the same `/api/...` routes the UI does, so
every guard (validation, demo lock, daily caps) applies to the agent too.
"""

import time
from dataclasses import dataclass
from typing import Any, NamedTuple

import httpx

from app import events


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

    async def get_bytes(self, path: str) -> bytes | None:
        """The raw body of a 200 response (e.g. an image), else None."""
        response = await self._http().request("GET", path)
        return response.content if response.status_code == 200 else None

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
    `OPTION_NOT_ON_BOARD` error. The option carries `exploration_item_id`: the item explored."""
    status, body = await ctx.api.get(f"/api/boards/{ctx.board_id}/explorations")
    if status != 200:
        return api_error(status, body)
    for exploration in body["explorations"]:
        for option in exploration["options"]:
            if option["id"] == option_id:
                return {**option, "exploration_item_id": exploration["item_id"]}
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


async def _await_job(
    sub: events.AsyncSubscription, job_id: str, done: str, failed: str, timeout_s: float
) -> dict[str, Any] | None:
    """The finishing event's result for `job_id` (`done` or `failed`), or None on timeout."""
    deadline = time.monotonic() + timeout_s
    while (left := deadline - time.monotonic()) > 0:
        event = await sub.aget(left)
        if event is None:
            return None
        data = event["data"]
        if data.get("job_id") != job_id:
            continue
        if event["type"] == done:
            return {
                "job_id": job_id, "item_id": data["item_id"], "item_ids": [data["item_id"]],
                "check": data.get("check"),
            }  # fmt: skip
        if event["type"] == failed:
            return {
                "error": str(data.get("code") or "JOB_FAILED"),
                "message": str(data.get("message") or ""),
                "job_id": job_id,
            }
    return None


async def queue_and_wait(
    ctx: ToolContext, path: str, body: dict[str, Any], done: str, failed: str, timeout_s: float
) -> dict[str, Any]:
    """Post a job that answers 202 `{"job_id"}` and wait for its `done`/`failed` board event.

    Subscribes before posting: under JOBS_SYNC (and on a fast mock) the job finishes inside the
    POST, so its events are already queued when we start listening. On timeout the job id comes
    back with a hint to `wait(kind="job")`.
    """
    assert ctx.board_id is not None
    sub = events.subscribe_async(ctx.board_id)
    try:
        status, res = await ctx.api.post(path, json=body)
        if status != 202:
            return api_error(status, res)
        job_id = str(res["job_id"])
        seen = await _await_job(sub, job_id, done, failed, timeout_s)
    finally:
        sub.close()
    if seen is None:
        return {"job_id": job_id, "timed_out": True, "hint": "wait(kind='job', id=job_id)"}
    return seen
