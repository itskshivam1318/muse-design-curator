from typing import Any

from app.agent.context import ToolContext, api_error, place

DEFINITION = {
    "name": "add_reference",
    "description": "Add a reference to the board from a web address (a page or an image link). "
    "Without x and y it goes in the next free spot.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Address of the page or image."},
            "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "required": ["url"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    at = await place(ctx, args)
    if isinstance(at, dict):
        return at
    body = {"url": args.get("url"), "x": at[0], "y": at[1]}
    status, res = await ctx.api.post(f"/api/boards/{ctx.board_id}/items", json=body)
    if status != 201:
        return api_error(status, res)
    item = res["item"]
    return {"item_id": item["id"], "deduped": res["deduped"], "item_ids": [item["id"]]}
