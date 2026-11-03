import asyncio
import math
import time
from typing import Any

from app.agent.context import ToolContext, api_error, board_items, require_option

KINDS = ("item", "analysis", "option", "note", "plugin_run")
POLL_S = 1.0
TIMEOUT_MIN, TIMEOUT_MAX, TIMEOUT_DEFAULT = 1.0, 120.0, 60.0

DEFINITION = {
    "name": "wait",
    "description": "Wait for something queued to finish: an item being read (item), an analysis "
    "(analysis), a visualized option (option), a visualized note (note) or a plugin run "
    "(plugin_run). Polls until it is no longer busy or timeout_s passes. For option and note the "
    "result has the new item's id and its check.",
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "id": {"type": "string", "description": "The item, option or plugin run id."},
            "timeout_s": {"type": "number", "default": 60, "description": "1 to 120 seconds."},
        },
        "required": ["kind", "id"],
    },
}

_Probe = tuple[bool, str, dict[str, Any]]  # busy, state, result
_FOCUS = ("item_id", "note_id")  # the result key naming the item to focus, first found


def clamp_timeout(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return TIMEOUT_DEFAULT
    if math.isnan(seconds):
        return TIMEOUT_DEFAULT
    return min(max(seconds, TIMEOUT_MIN), TIMEOUT_MAX)


def _find(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((i for i in items if i["id"] == item_id), None)


def _newest_child(items: list[dict[str, Any]], **match: Any) -> dict[str, Any] | None:
    found = [i for i in items if all(i.get(k) == v for k, v in match.items())]
    return max(found, key=lambda i: i["created_at"], default=None)


def _produced(item: dict[str, Any] | None) -> dict[str, Any]:
    if item is None:
        return {"item_id": None, "check": None}
    return {"item_id": item["id"], "check": item.get("check")}


async def _item(ctx: ToolContext, item_id: str) -> _Probe | dict[str, Any]:
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    item = _find(items, item_id)
    if item is None:
        return {"error": "ITEM_NOT_ON_BOARD", "message": f"{item_id} is not on the open board."}
    state = item["parse_status"]
    return state in ("pending", "processing"), state, {"item_id": item_id, "check": item["check"]}


async def _analysis(ctx: ToolContext, item_id: str) -> _Probe | dict[str, Any]:
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    if _find(items, item_id) is None:
        return {"error": "ITEM_NOT_ON_BOARD", "message": f"{item_id} is not on the open board."}
    status, res = await ctx.api.get(f"/api/items/{item_id}/analysis")
    if status != 200:
        return api_error(status, res)
    state = res["parse_status"]
    return state in ("pending", "processing"), state, {"item_id": item_id, **res}


async def _option(ctx: ToolContext, option_id: str) -> _Probe | dict[str, Any]:
    option = await require_option(ctx, option_id)
    if "error" in option:
        return option
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    made = _newest_child(items, explore_option_id=option_id)
    return (
        option["status"] == "visualizing",
        option["status"],
        {
            "option_id": option_id,
            "last_error": option["last_error"],
            **_produced(made),
        },
    )


async def _note(ctx: ToolContext, note_id: str) -> _Probe | dict[str, Any]:
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    note = _find(items, note_id)
    if note is None or note["kind"] != "note":
        return {"error": "ITEM_NOT_ON_BOARD", "message": f"{note_id} is not a note on this board."}
    busy = bool((note.get("generation") or {}).get("visualizing_since"))
    made = _newest_child(items, parent_item_id=note_id, origin="generated")
    return busy, "visualizing" if busy else "idle", {"note_id": note_id, **_produced(made)}


async def _plugin_run(ctx: ToolContext, run_id: str) -> _Probe | dict[str, Any]:
    status, res = await ctx.api.get(f"/api/plugin-runs/{run_id}")
    if status != 200:
        return api_error(status, res)
    status, nodes = await ctx.api.get(f"/api/boards/{ctx.board_id}/nodes")
    if status != 200:
        return api_error(status, nodes)
    if res["node_id"] not in {n["id"] for n in nodes["nodes"]}:
        return {"error": "RUN_NOT_ON_BOARD", "message": f"{run_id} is not a run on this board."}
    return res["status"] in ("queued", "running"), res["status"], res


_PROBES = {
    "item": _item,
    "analysis": _analysis,
    "option": _option,
    "note": _note,
    "plugin_run": _plugin_run,
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    kind = args.get("kind")
    probe = _PROBES.get(str(kind))
    if probe is None:
        return {"error": "BAD_KIND", "message": f"kind is one of {', '.join(KINDS)}."}
    target = str(args.get("id") or "")
    deadline = time.monotonic() + clamp_timeout(args.get("timeout_s"))
    while True:
        seen = await probe(ctx, target)
        if isinstance(seen, dict):
            return seen
        busy, state, result = seen
        if not busy:
            done = {"state": state, "result": result, "timed_out": False}
            focus = next((result[k] for k in _FOCUS if result.get(k)), None)
            return {**done, "item_ids": [focus]} if focus else done
        if time.monotonic() >= deadline:
            return {"state": state, "result": None, "timed_out": True}
        await asyncio.sleep(POLL_S)
