from typing import Any

from app.agent.context import ToolContext, api_error

DEFINITION = {
    "name": "read_board",
    "description": "Read the open board: its details, up to 200 items (newest first) with "
    "position, role, analysis state and any result check, the board profile, and the context.",
    "parameters": {"type": "object", "properties": {}},
}
ITEM_CAP = 200
_KEYS = ("id", "kind", "role", "x", "y", "w", "h", "parse_status", "check")
_PARTS = (("board", ""), ("items", "/items"), ("profile", "/profile"), ("context", "/context"))


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item.get(k) for k in _KEYS}
    if item.get("note_text") is not None:
        out["note_text"] = item["note_text"]
    return out


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    parts = {}
    for name, suffix in _PARTS:
        status, res = await ctx.api.get(f"/api/boards/{ctx.board_id}{suffix}")
        if status != 200:
            return api_error(status, res)
        parts[name] = res
    items = sorted(parts["items"]["items"], key=lambda i: i["created_at"], reverse=True)
    return {
        "board": parts["board"],
        "items": [_summary(i) for i in items[:ITEM_CAP]],
        "profile": parts["profile"],
        "context": parts["context"],
    }
