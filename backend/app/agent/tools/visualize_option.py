from typing import Any

from app.agent.context import ToolContext, api_error, require_option

DEFINITION = {
    "name": "visualize_option",
    "description": "Render an explore option as an image on the board. Queued; use wait "
    "(kind option) to get the new item and its check.",
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
    status, res = await ctx.api.post(f"/api/options/{option_id}/visualize")
    if status != 202:
        return api_error(status, res)
    return {"queued": True, "option_id": option_id}
