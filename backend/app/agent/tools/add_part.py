from typing import Any

from app.agent.context import ToolContext, api_error, require_item

DEFINITION = {
    "name": "add_part",
    "description": "Add a part to a picture (a named piece such as 'front wheel') and find where "
    "it is. Pass box as fractions of the picture, [x0, y0, x1, y1], to point at it; without a "
    "box Muse looks for it by name. If nothing is found the part is not kept.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "label": {"type": "string", "description": "The part's name, such as 'front wheel'."},
            "box": {
                "type": "array",
                "items": {"type": "number", "minimum": 0, "maximum": 1},
                "minItems": 4,
                "maxItems": 4,
                "description": "[x0, y0, x1, y1] as fractions of the picture, 0 to 1.",
            },
        },
        "required": ["item_id", "label"],
    },
}


def _box(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
        return None
    x0, y0, x1, y1 = (float(v) for v in raw)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    return [x0, y0, x1, y1]


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    item_id = str(args.get("item_id") or "")
    item = await require_item(ctx, item_id)
    if "error" in item:
        return item
    body: dict[str, Any] = {"label": args.get("label"), "region": None}
    if args.get("box") is not None:
        box = _box(args["box"])
        if box is None:
            return {
                "error": "BAD_BOX",
                "message": "box is [x0, y0, x1, y1] as fractions from 0 to 1, with x0 < x1 and "
                "y0 < y1.",
            }
        body["region"] = {"kind": "mask", "box": box}
    status, part = await ctx.api.post(f"/api/items/{item_id}/parts", json=body)
    if status != 201:
        return api_error(status, part)
    status, region = await ctx.api.get(f"/api/items/{item_id}/parts/{part['key']}/region")
    if status != 200:
        failure = api_error(status, region)
        await ctx.api.delete(f"/api/items/{item_id}/parts/{part['key']}")
        if failure["error"] == "REGION_EMPTY":
            return {
                "error": "REGION_EMPTY",
                "message": "Nothing found for this part; try a shorter name or draw a box.",
            }
        return failure
    return {"part": part, "region": region, "item_ids": [item_id]}
