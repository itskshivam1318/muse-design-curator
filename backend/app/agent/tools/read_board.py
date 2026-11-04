from collections import Counter
from typing import Any

from app.agent.context import ToolContext, api_error

DEFINITION = {
    "name": "read_board",
    "description": "Read the open board: its details, up to 60 items (newest first) with origin "
    "(upload, generated, ...), a short title, position, role, analysis state, any result check "
    "and, for a made picture, the picture it came from (parent_item_id, put_source_item_id, "
    "extracted_part); item counts by origin; the board profile and the context.",
    "parameters": {"type": "object", "properties": {}},
}
ITEM_CAP = 60
TITLE_CHARS = 80
_KEYS = ("id", "kind", "origin", "role", "x", "y", "w", "h", "parse_status", "check")
_LINKS = ("parent_item_id", "put_source_item_id", "extracted_part")  # listed only when set
_PARTS = (("board", ""), ("items", "/items"), ("profile", "/profile"), ("context", "/context"))


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item.get(k) for k in _KEYS}
    title = item.get("page_title") or item.get("original_filename")
    if title:
        out["title"] = title[:TITLE_CHARS]
    out.update({k: item[k] for k in _LINKS if item.get(k) is not None})
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
    shown = [_summary(i) for i in items[:ITEM_CAP]]
    return {
        "board": parts["board"],
        "items": shown,
        "item_counts": {
            "total": len(items),
            "shown": len(shown),
            "by_origin": dict(Counter(str(i.get("origin")) for i in items)),
        },
        "profile": parts["profile"],
        "context": parts["context"],
    }
