from typing import Any

from starlette.concurrency import run_in_threadpool

from app.agent.context import ToolContext, api_error
from app.api.deps import new_session
from app.db.repos import agent as agent_repo

DEFINITION = {
    "name": "open_board",
    "description": "Open an existing board to work on it. Returns a summary of the board.",
    "parameters": {
        "type": "object",
        "properties": {"board_id": {"type": "string", "description": "The board's id."}},
        "required": ["board_id"],
    },
}
NEEDS_BOARD = False


def _open_run_id(board_id: str) -> str | None:
    with new_session() as session:
        run = agent_repo.open_run(session, board_id)
        return run.id if run is not None else None


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    board_id = str(args.get("board_id") or "")
    status, board = await ctx.api.get(f"/api/boards/{board_id}")
    if status != 200:
        return api_error(status, board)
    status, items = await ctx.api.get(f"/api/boards/{board_id}/items")
    if status != 200:
        return api_error(status, items)
    ctx.board_id = board_id
    ctx.run_id = await run_in_threadpool(_open_run_id, board_id)
    return {**board, "items": len(items["items"]), "run_id": ctx.run_id}
