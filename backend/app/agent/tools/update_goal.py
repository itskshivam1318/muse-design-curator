from typing import Any

from app.agent import run_state
from app.agent.context import ToolContext
from app.agent.tools.set_goal import (
    DELIVERABLE_LEN,
    DELIVERABLES_MAX,
    GOAL_MAX,
    _deliverables,
)

DEFINITION = {
    "name": "update_goal",
    "description": "Change the open run's goal, its deliverables, or both, when the person "
    "redirects you. Pass only what changes; the deliverables you pass replace the old list.",
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": f"Up to {GOAL_MAX} characters."},
            "deliverables": {
                "type": "array",
                "items": {"type": "string", "maxLength": DELIVERABLE_LEN},
                "minItems": 1,
                "maxItems": DELIVERABLES_MAX,
                "description": f"1 to {DELIVERABLES_MAX} distinct names, each up to "
                f"{DELIVERABLE_LEN} characters.",
            },
        },
    },
}


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if args.get("goal") is not None:
        goal = args["goal"].strip() if isinstance(args["goal"], str) else ""
        if not 0 < len(goal) <= GOAL_MAX:
            return {"error": "BAD_GOAL", "message": f"The goal is 1 to {GOAL_MAX} characters."}
        fields["goal"] = goal
    if args.get("deliverables") is not None:
        deliverables = _deliverables(args["deliverables"])
        if deliverables is None:
            return {
                "error": "BAD_DELIVERABLES",
                "message": f"Give 1 to {DELIVERABLES_MAX} distinct deliverable names, each 1 to "
                f"{DELIVERABLE_LEN} characters.",
            }
        fields["deliverables_json"] = deliverables
    if not fields:
        return {"error": "NOTHING_TO_UPDATE", "message": "Pass a goal, deliverables, or both."}
    assert ctx.board_id is not None
    current = await run_state.current(ctx.board_id, ctx.run_id, ctx.source)
    if current is None:
        return run_state.no_run()
    ctx.run_id = current["id"]
    data = await run_state.update(current["id"], **fields)
    return {"run_id": data["id"], "goal": data["goal"], "deliverables": data["deliverables"]}
