from typing import Any

from app.agent.context import ToolContext, api_error

DEFINITION = {
    "name": "propose_lens",
    "description": "Propose the lens (the set of things to look at in each reference) for the "
    "board, from what is on it. Returns the proposal; confirm it with set_lens.",
    "parameters": {"type": "object", "properties": {}},
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    status, res = await ctx.api.post(f"/api/boards/{ctx.board_id}/lens:propose")
    if status != 200:
        return api_error(status, res)
    return {"lens": res}
