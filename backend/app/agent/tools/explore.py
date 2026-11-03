from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "explore",
    "description": "Ask Muse for named options along one dimension of an item (for example "
    "other values it could take). Returns the options; visualize_option makes one into an image.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "dimension": {"type": "string", "description": "The dimension key (see get_analysis)."},
            "steer": {"type": "string", "description": "A hint for the options, up to 200 chars."},
            "mode": {
                "type": "string",
                "enum": ["initial", "more", "further"],
                "default": "initial",
            },
            "parent_option_id": {"type": "string", "description": "Explore further from this one."},
        },
        "required": ["item_id", "dimension"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    body: dict[str, Any] = {"key": args.get("dimension")}
    for field in ("steer", "mode", "parent_option_id"):
        if args.get(field) is not None:
            body[field] = args[field]
    status, res = await ctx.api.post(f"/api/items/{item_id}/explore", json=body)
    if status != 200:
        return api_error(status, res)
    return {
        "exploration_id": res["id"],
        "options": [
            {k: o[k] for k in ("id", "name", "description", "distance", "status", "batch")}
            for o in res["options"]
        ],
        "item_ids": [item_id],
    }
