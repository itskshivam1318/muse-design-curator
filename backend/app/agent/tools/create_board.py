from typing import Any

from app.agent.context import ToolContext, api_error

DEFINITION = {
    "name": "create_board",
    "description": "Create a new board and open it. Give the board a title and, when you know "
    "it, the context it is for and a domain.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The board's title."},
            "context": {"type": "string", "description": "What the board is for."},
            "domain": {"type": "string", "description": "The board's domain, if known."},
        },
        "required": ["title"],
    },
}
NEEDS_BOARD = False


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    body = {k: args[k] for k in ("title", "context", "domain") if args.get(k) is not None}
    status, res = await ctx.api.post("/api/boards", json=body)
    if status != 201:
        return api_error(status, res)
    ctx.board_id = res["id"]
    ctx.run_id = None  # a new board has no run yet; the previous board's run stays there
    return {"board_id": res["id"]}
