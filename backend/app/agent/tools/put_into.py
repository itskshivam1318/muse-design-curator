from typing import Any

from app.agent.context import ToolContext, queue_and_wait, require_item
from app.agent.tools.wait import TIMEOUT_DEFAULT_JOB, clamp_timeout

DEFINITION = {
    "name": "put_into",
    "description": "Put one picture into another: draw the source picture's subject into the "
    "target picture at the given spots. A spot is a part key from get_analysis of the target "
    "({'part': 'front_wheel'}) or a point as fractions of the target ({'point': {'fx': 0.5, "
    "'fy': 0.5}}); at most 8. The result is a new picture beside the target. Waits for it (up to "
    "timeout_s, default 90); if it is not ready, the job id comes back and wait(kind='job') "
    "picks it up.",
    "parameters": {
        "type": "object",
        "properties": {
            "target_id": {"type": "string", "description": "The picture to put it into."},
            "source_id": {"type": "string", "description": "The picture to put in."},
            "spots": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {"type": "object"},
                "description": "Each {'part': key} or {'point': {'fx': 0..1, 'fy': 0..1}}.",
            },
            "words": {"type": "string", "description": "Optional extra guidance."},
            "timeout_s": {"type": "number", "default": 90, "description": "1 to 120 seconds."},
        },
        "required": ["target_id", "source_id", "spots"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    target_id = str(args.get("target_id") or "")
    source_id = str(args.get("source_id") or "")
    for item_id in (target_id, source_id):
        item = await require_item(ctx, item_id)
        if "error" in item:
            return item
    body = {"source_id": source_id, "spots": args.get("spots"), "words": args.get("words")}
    timeout = clamp_timeout(args.get("timeout_s", TIMEOUT_DEFAULT_JOB))
    return await queue_and_wait(
        ctx, f"/api/items/{target_id}/put-into", body, "put.done", "put.failed", timeout
    )
