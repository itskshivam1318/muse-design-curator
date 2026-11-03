from typing import Any

from app.agent.context import ToolContext, api_error

DEFINITION = {
    "name": "list_boards",
    "description": "List the boards, most recently changed first, with their item counts.",
    "parameters": {"type": "object", "properties": {}},
}
NEEDS_BOARD = False


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    status, res = await ctx.api.get("/api/boards")
    if status != 200:
        return api_error(status, res)
    boards = []
    for b in res["boards"]:
        board = (await ctx.api.get(f"/api/boards/{b['id']}")).body
        items = (await ctx.api.get(f"/api/boards/{b['id']}/items")).body
        boards.append(
            {
                "id": b["id"],
                "title": b["title"],
                "domain": board.get("domain") if isinstance(board, dict) else None,
                "items": len(items["items"]) if isinstance(items, dict) else 0,
            }
        )
    return {"boards": boards}
