from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "remove_part",
    "description": "Remove a part from a picture.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "part": {"type": "string", "description": "The part key from get_analysis."},
        },
        "required": ["item_id", "part"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    part = str(args.get("part") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    status, res = await ctx.api.delete(f"/api/items/{item_id}/parts/{part}")
    if status != 204:
        return api_error(status, res)
    return {"removed": part, "item_ids": [item_id]}
