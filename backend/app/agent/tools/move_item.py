from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "move_item",
    "description": "Move an item on the board to a position.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "required": ["item_id", "x", "y"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    status, res = await ctx.api.patch(
        f"/api/items/{item_id}", json={"x": args.get("x"), "y": args.get("y")}
    )
    if status != 200:
        return api_error(status, res)
    return {"item_id": item_id, "x": res["x"], "y": res["y"], "item_ids": [item_id]}
