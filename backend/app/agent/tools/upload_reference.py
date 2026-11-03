from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.agent.context import ToolContext, api_error, place
from app.config import get_settings
from app.ingest.sniff import sniff_image

DEFINITION = {
    "name": "upload_reference",
    "description": "Add a local image file to the board as a reference. Optionally record the "
    "page address it came from. Without x and y it goes in the next free spot.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of an image file on this machine."},
            "page_url": {"type": "string", "description": "Page the image came from."},
            "x": {"type": "number"},
            "y": {"type": "number"},
        },
        "required": ["path"],
    },
}
MCP_ONLY = True


def _read(path: str) -> tuple[bytes, str] | dict[str, Any]:
    p = Path(path).expanduser()
    if not p.is_file():
        return {"error": "FILE_NOT_FOUND", "message": f"No file at {path}."}
    limit = get_settings().MAX_UPLOAD_BYTES
    if p.stat().st_size > limit:
        return {"error": "FILE_TOO_LARGE", "message": f"The file is over {limit} bytes."}
    data = p.read_bytes()
    sniffed = sniff_image(data)
    if sniffed is None:
        return {"error": "UNSUPPORTED_MEDIA_TYPE", "message": "Only image files can be added."}
    return data, sniffed[0]


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path") or "")
    read = await run_in_threadpool(_read, path)
    if isinstance(read, dict):
        return read
    data, mime = read
    at = await place(ctx, args)
    if isinstance(at, dict):
        return at
    fields = {"x": str(at[0]), "y": str(at[1])}
    if args.get("page_url"):
        fields["page_url"] = str(args["page_url"])
    status, res = await ctx.api.post(
        f"/api/boards/{ctx.board_id}/items",
        files=[("files[]", (Path(path).name, data, mime))],
        data=fields,
    )
    if not isinstance(res, dict) or "results" not in res:
        return api_error(status, res)
    first = res["results"][0]
    if not first["ok"]:
        return {"error": first["error"]["code"], "message": first["error"]["message"]}
    item_id = first["item"]["id"]
    return {"item_id": item_id, "deduped": first["deduped"], "item_ids": [item_id]}
