from typing import Any

from app.agent.context import ToolContext, api_error

DEFINITION = {
    "name": "set_lens",
    "description": "Confirm a proposed lens as the board's lens.",
    "parameters": {
        "type": "object",
        "properties": {"lens_id": {"type": "string", "description": "The proposed lens's id."}},
        "required": ["lens_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    lens_id = str(args.get("lens_id") or "")
    status, res = await ctx.api.get(f"/api/boards/{ctx.board_id}/lens")
    if status != 200:
        return api_error(status, res)
    current = res["lens"]
    body = None
    if current is None or current["id"] != lens_id:
        # a proposal made while the board already uses a lens (its domain's curated one) is not
        # the board's lens yet: confirm it by sending its spec
        status, proposed = await ctx.api.get(f"/api/lenses/{lens_id}")
        mine = status == 200 and proposed["board_id"] == ctx.board_id
        if not mine or proposed["status"] != "proposed":
            return {"error": "LENS_NOT_FOUND", "message": f"{lens_id} is not this board's lens."}
        body = proposed["spec"]
    status, res = await ctx.api.put(f"/api/boards/{ctx.board_id}/lens", json=body)
    if status != 200:
        return api_error(status, res)
    return {"lens": res}
