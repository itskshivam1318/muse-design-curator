from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "get_analysis",
    "description": "What Muse sees in an item: its dimensions (key, label, type, value, "
    "confidence) and its parts.",
    "parameters": {
        "type": "object",
        "properties": {"item_id": {"type": "string", "description": "The item's id."}},
        "required": ["item_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    status, res = await ctx.api.get(f"/api/items/{item_id}/analysis")
    if status != 200:
        return api_error(status, res)
    return {**res, "item_ids": [item_id]}
