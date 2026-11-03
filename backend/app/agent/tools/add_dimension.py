from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "add_dimension",
    "description": "Add a dimension of your own to an item (something to read off it, such as "
    "'Warmth'). Its key comes from the label. Pass value to set it straight away.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "label": {"type": "string", "description": "Up to 80 characters."},
            "type": {
                "type": "string",
                "enum": ["physical", "abstract"],
                "default": "abstract",
                "description": "Physical reads a part of the item; abstract reads the whole.",
            },
            "part": {"type": "string", "description": "The part key, for a physical dimension."},
            "prompt": {"type": "string", "description": "How to read it, up to 300 characters."},
            "kind": {"type": "string", "default": "text", "description": "Such as text, color."},
            "value": {"description": "The value to set (string, number or boolean)."},
        },
        "required": ["item_id", "label"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    body = {"label": args.get("label"), "type": args.get("type") or "abstract"}
    for field in ("part", "prompt", "kind"):
        if args.get(field) is not None:
            body[field] = args[field]
    status, res = await ctx.api.post(f"/api/items/{item_id}/dimensions", json=body)
    if status != 201:
        return api_error(status, res)
    if args.get("value") is not None:
        status, res = await ctx.api.patch(
            f"/api/items/{item_id}/attributes/{res['key']}", json={"value": args["value"]}
        )
        if status != 200:
            return api_error(status, res)
    return {"dimension": res, "item_ids": [item_id]}
