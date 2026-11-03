from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "visualize_note",
    "description": "Turn a note into an image placed beside it. The image appears on the board "
    "once it is made.",
    "parameters": {
        "type": "object",
        "properties": {"note_id": {"type": "string", "description": "The note's item id."}},
        "required": ["note_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    note_id = str(args.get("note_id") or "")
    item = await require_item(ctx, note_id)
    if "error" in item:
        return item
    status, res = await ctx.api.post(f"/api/items/{note_id}/visualize")
    if status != 202:
        return api_error(status, res)
    return {"queued": True, "item_ids": [note_id]}
