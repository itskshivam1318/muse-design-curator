import asyncio
from typing import Any

from app.agent.context import ToolContext
from app.agent.tools import wait

IDS_MAX = 6

DEFINITION = {
    "name": "wait_all",
    "description": "Wait for several things of one kind at once (the same kinds as wait). Each is "
    f"polled until it is no longer busy or timeout_s passes; at most {IDS_MAX}. The result has "
    "one wait result per id.",
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(wait.KINDS)},
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": IDS_MAX,
            },
            "timeout_s": {"type": "number", "default": 120, "description": "1 to 120 seconds."},
        },
        "required": ["kind", "ids"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("ids")
    ids = list(dict.fromkeys(str(i) for i in raw)) if isinstance(raw, list) else []
    if not 1 <= len(ids) <= IDS_MAX:
        return {"error": "BAD_IDS", "message": f"Give 1 to {IDS_MAX} ids."}
    timeout = args.get("timeout_s", wait.TIMEOUT_MAX)
    results = await asyncio.gather(
        *(wait.run(ctx, {"kind": args.get("kind"), "id": i, "timeout_s": timeout}) for i in ids)
    )
    focus = list(dict.fromkeys(f for r in results for f in r.get("item_ids", [])))
    return {"results": dict(zip(ids, results, strict=True)), "item_ids": focus}
