from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "analyse",
    "description": "Have Muse read an item: what it is, its parts and its dimensions. Queued; "
    "use wait (kind analysis) for it to finish, then get_analysis. Counts against the board's "
    "daily analysis limit.",
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
    status, res = await ctx.api.post(f"/api/items/{item_id}/analyse")
    if status != 202:
        return api_error(status, res)
    return {"queued": True, "parse_status": res["parse_status"], "item_ids": [item_id]}
