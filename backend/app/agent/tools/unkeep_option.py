from typing import Any

from app.agent.context import ToolContext, api_error, require_option

DEFINITION = {
    "name": "unkeep_option",
    "description": "Undo keep_option: the kept take goes back to staging.",
    "parameters": {
        "type": "object",
        "properties": {"option_id": {"type": "string"}},
        "required": ["option_id"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    option_id = str(args.get("option_id") or "")
    option = await require_option(ctx, option_id)
    if "error" in option:
        return option
    status, res = await ctx.api.post(f"/api/options/{option_id}/unkeep")
    if status != 200:
        return api_error(status, res)
    return {"option_id": option_id, "status": res["status"]}
