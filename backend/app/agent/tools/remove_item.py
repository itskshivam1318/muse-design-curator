from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "remove_item",
    "description": "Remove an item from the board.",
    "parameters": {
        "type": "object",
        "properties": {"item_id": {"type": "string"}},
        "required": ["item_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    status, res = await ctx.api.delete(f"/api/items/{item_id}")
    if status != 204:
        return api_error(status, res)
    return {"removed": item_id}
