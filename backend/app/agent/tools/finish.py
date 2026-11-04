from typing import Any

from starlette.concurrency import run_in_threadpool

from app.agent import checks, run_state
from app.agent.context import ToolContext, board_items
from app.providers.reasoning import MAX_STRUCTURED_IMAGES

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
    """The thumbnails of the output items that have one (notes do not), with their ids; at most
    the first MAX_STRUCTURED_IMAGES, as many as the consistency check looks at. Thumbnails
    are enough to tell one design from another and keep the model call small."""
    images: list[bytes] = []
    shown: list[str] = []
    for item_id in item_ids:
        if len(images) >= MAX_STRUCTURED_IMAGES:
            break
        response = await ctx.api.get_bytes(f"/api/items/{item_id}/image?size=thumb")
        if response is not None:
            images.append(response)
            shown.append(item_id)
    return images, shown


async def _problems(ctx: ToolContext, run: dict[str, Any]) -> list[str] | dict[str, Any]:
    """Deliverable problems; only when there are none, the consistency check, which runs only
    with at least 2 output images (one image has nothing to be inconsistent with)."""
    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    problems = checks.deliverable_problems(run, {i["id"]: i for i in items})
    if problems:
        return problems
    images, shown = await _images(ctx, checks.output_item_ids(run, compared=True))
    if len(images) < 2:  # nothing to compare
        return []
    try:
        return await run_in_threadpool(checks.consistency_problems, images, run["goal"], shown)
    except checks.CheckUnavailable as e:  # not the output's fault: no refusal is used up
        return {
            "error": "CHECK_UNAVAILABLE",
            "message": f"The consistency check could not run ({e}); call finish again.",
        }


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    summary = args.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    if not 0 < len(summary) <= SUMMARY_MAX:
        return {"error": "BAD_SUMMARY", "message": f"The summary is 1 to {SUMMARY_MAX} characters."}
    assert ctx.board_id is not None
    current = await run_state.current(ctx.board_id, ctx.run_id, ctx.source)
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
        return _waiting(problems)
    refusals = current["finish_refusals"] + 1
    if refusals < REFUSALS_MAX:
        await run_state.update(current["id"], finish_refusals=refusals)
        return {
            "error": "OUTPUT_NOT_READY",
            "message": f"The output is not ready (refusal {refusals} of {REFUSALS_MAX}).",
            "problems": problems,
        }
    await run_state.update(current["id"], finish_refusals=refusals, status="needs_input")
    return _waiting(problems)


def _waiting(problems: list[str]) -> dict[str, Any]:
    """Refused for good: the run waits for the person. Still an error, so its step reads failed."""
    return {
        "error": "OUTPUT_NOT_READY",
        "message": f"The output is not ready after {REFUSALS_MAX} refusals; the run waits for "
        "the person.",
        "status": "needs_input",
        "problems": problems,
    }
