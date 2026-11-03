from typing import Any

from starlette.concurrency import run_in_threadpool

from app.agent import checks, run_state
from app.agent.context import ToolContext, board_items

REFUSALS_MAX = 3
SUMMARY_MAX = 2000

DEFINITION = {
    "name": "finish",
    "description": "End the run. Muse first checks the output sheet: every deliverable has items, "
    "each still on the board and passing its result check, and the images show one design. If "
    "anything is wrong it refuses and lists the problems; fix them and call finish again. After "
    f"{REFUSALS_MAX} refusals the run waits for the person.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": f"What the output shows, for the person (up to {SUMMARY_MAX} "
                "characters).",
            },
        },
        "required": ["summary"],
    },
}


async def _images(ctx: ToolContext, item_ids: list[str]) -> tuple[list[bytes], list[str]]:
    """The images of the output items that have one (notes do not), with their ids."""
    images: list[bytes] = []
    shown: list[str] = []
    for item_id in item_ids:
        response = await ctx.api.get_bytes(f"/api/items/{item_id}/image?size=full")
        if response is not None:
            images.append(response)
            shown.append(item_id)
    return images, shown


async def _problems(ctx: ToolContext, run: dict[str, Any]) -> list[str] | dict[str, Any]:
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    problems = checks.deliverable_problems(run, {i["id"]: i for i in items})
    if problems:
        return problems
    images, shown = await _images(ctx, checks.output_item_ids(run))
    if len(images) < 2:  # nothing to compare
        return []
    return await run_in_threadpool(checks.consistency_problems, images, run["goal"], shown)


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    summary = args.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    if not 0 < len(summary) <= SUMMARY_MAX:
        return {"error": "BAD_SUMMARY", "message": f"The summary is 1 to {SUMMARY_MAX} characters."}
    assert ctx.board_id is not None
    current = await run_state.current(ctx.board_id, ctx.run_id)
    if current is None:
        return run_state.no_run()
    ctx.run_id = current["id"]

    problems = await _problems(ctx, current)
    if isinstance(problems, dict):
        return problems
    if not problems:
        await run_state.update(current["id"], status="done", note=summary)
        return {"status": "done"}
    if current["finish_refusals"] >= REFUSALS_MAX:  # already waiting for the person
        return {"status": "needs_input", "problems": problems}
    refusals = current["finish_refusals"] + 1
    if refusals < REFUSALS_MAX:
        await run_state.update(current["id"], finish_refusals=refusals)
        return {
            "error": "OUTPUT_NOT_READY",
            "message": f"The output is not ready (refusal {refusals} of {REFUSALS_MAX}).",
            "problems": problems,
        }
    await run_state.update(current["id"], finish_refusals=refusals, status="needs_input")
    return {"status": "needs_input", "problems": problems}
