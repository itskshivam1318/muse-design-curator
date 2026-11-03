from typing import Any

from app.agent.context import ToolContext, api_error, place, require_item

DEFINITION = {
    "name": "run_plugin",
    "description": "Run a plugin on items of the board (it is added to the board if needed). "
    "Queued; use wait (kind plugin_run) with the returned run_id.",
    "parameters": {
        "type": "object",
        "properties": {
            "plugin_id": {"type": "string"},
            "input_item_ids": {"type": "array", "items": {"type": "string"}, "default": []},
            "params": {"type": "object", "description": "The plugin's own settings."},
            "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "required": ["plugin_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    inputs = [str(i) for i in args.get("input_item_ids") or []]
    for item_id in inputs:
        item = await require_item(ctx, item_id)
        if "error" in item:
            return item
    at = await place(ctx, args)
    if isinstance(at, dict):
        return at
    plugin_id = args.get("plugin_id")
    board = f"/api/boards/{ctx.board_id}"
    status, res = await ctx.api.post(f"{board}/plugins", json={"plugin_id": plugin_id})
    if status != 200:
        return api_error(status, res)
    body = {"plugin_id": plugin_id, "x": at[0], "y": at[1], "input_item_ids": inputs}
    status, node = await ctx.api.post(f"{board}/nodes", json=body)
    if status != 201:
        return api_error(status, node)
    if args.get("params"):
        patch = {"params": args["params"]}
        status, res = await ctx.api.patch(f"/api/nodes/{node['id']}", json=patch)
        if status != 200:
            return api_error(status, res)
    status, started = await ctx.api.post(f"/api/nodes/{node['id']}/run")
    if status != 202:
        return api_error(status, started)
    return {
        "node_id": node["id"],
        "run_id": started["id"],
        "status": started["status"],
        "item_ids": inputs,
    }
