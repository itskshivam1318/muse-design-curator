from typing import Any

from app.agent.context import ToolContext, queue_and_wait, require_item
from app.agent.tools.wait import TIMEOUT_DEFAULT_JOB, clamp_timeout

DEFINITION = {
    "name": "render_view",
    "description": "Draw the same design again from another viewpoint. The result is a new "
    "picture placed beside the anchor picture. The view is plain words, e.g. 'from the front "
    "left at three-quarters', 'from the rear', 'seen from inside, from the open door'. It keeps "
    "the design but may drift in small details: check the result with your own eyes or with "
    "`finish`. Waits for the picture (up to timeout_s, default 90); if it is not ready, the job "
    "id comes back and wait(kind='job') picks it up.",
    "parameters": {
        "type": "object",
        "properties": {
            "anchor_id": {"type": "string", "description": "The picture's item id."},
            "view": {"type": "string", "description": "The viewpoint, 1 to 120 characters."},
            "words": {"type": "string", "description": "Optional extra guidance, up to 200."},
            "timeout_s": {"type": "number", "default": 90, "description": "1 to 120 seconds."},
        },
        "required": ["anchor_id", "view"],
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    anchor_id = str(args.get("anchor_id") or "")
    item = await require_item(ctx, anchor_id)
    if "error" in item:
        return item
    body = {"view": args.get("view"), "words": args.get("words")}
    timeout = clamp_timeout(args.get("timeout_s", TIMEOUT_DEFAULT_JOB))
    return await queue_and_wait(
        ctx, f"/api/items/{anchor_id}/render-view", body, "view.done", "view.failed", timeout
    )
