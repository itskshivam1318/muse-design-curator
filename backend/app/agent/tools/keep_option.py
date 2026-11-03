from typing import Any

from app.agent.context import ToolContext, api_error, require_item, require_option

DEFINITION = {
    "name": "keep_option",
    "description": "Keep one rendered take of an option: it leaves the staging area and stays "
    "on the board.",
    "parameters": {
        "type": "object",
        "properties": {
            "option_id": {"type": "string"},
            "item_id": {"type": "string", "description": "The rendered take (an item id)."},
        },
        "required": ["option_id", "item_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    option_id = str(args.get("option_id") or "")
    item_id = str(args.get("item_id") or "")
    option = await require_option(ctx, option_id)
    if "error" in option:
        return option
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    status, res = await ctx.api.post(f"/api/options/{option_id}/keep", json={"item_id": item_id})
    if status != 200:
        return api_error(status, res)
    return {"option_id": option_id, "status": res["status"], "item_ids": [item_id]}
