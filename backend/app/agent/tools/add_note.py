from typing import Any

from app.agent.context import ToolContext, api_error, place

DEFINITION = {
    "name": "add_note",
    "description": "Add a text note to the board (a description of something to look for or "
    "make). Without x and y it goes in the next free spot.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The note, up to 2000 characters."},
            "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "required": ["text"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    at = await place(ctx, args)
    if isinstance(at, dict):
        return at
    body = {"text": args.get("text"), "x": at[0], "y": at[1]}
    status, res = await ctx.api.post(f"/api/boards/{ctx.board_id}/notes", json=body)
    if status != 201:
        return api_error(status, res)
    return {"item_id": res["id"], "item_ids": [res["id"]]}
