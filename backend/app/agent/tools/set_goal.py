from typing import Any

from app.agent import run_state
from app.agent.context import ToolContext

GOAL_MAX = 1000
DELIVERABLES_MAX = 12
DELIVERABLE_LEN = 80

DEFINITION = {
    "name": "set_goal",
    "description": "Start a run on the open board: the goal, and the deliverables the output must "
    "show (names such as 'front view'). Call this first; finish checks the output against these "
    "deliverables. If a run is already open on the board you join it instead, unless replace is "
    "true: then the open run is paused and a new one starts.",
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
            "replace": {
                "type": "boolean",
                "default": False,
                "description": "Pause the board's open run and start this one instead of "
                "joining it.",
            },
        },
        "required": ["goal", "deliverables"],
    },
}


def _deliverables(raw: Any) -> list[str] | None:
    if not isinstance(raw, list) or not 1 <= len(raw) <= DELIVERABLES_MAX:
        return None
    names = [d.strip() if isinstance(d, str) else "" for d in raw]
    if any(not 0 < len(n) <= DELIVERABLE_LEN for n in names) or len(set(names)) != len(names):
        return None
    return names


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    goal = args.get("goal")
    goal = goal.strip() if isinstance(goal, str) else ""
    if not 0 < len(goal) <= GOAL_MAX:
        return {"error": "BAD_GOAL", "message": f"The goal is 1 to {GOAL_MAX} characters."}
    deliverables = _deliverables(args.get("deliverables"))
    if deliverables is None:
        return {
            "error": "BAD_DELIVERABLES",
            "message": f"Give 1 to {DELIVERABLES_MAX} distinct deliverable names, each 1 to "
            f"{DELIVERABLE_LEN} characters.",
        }
    assert ctx.board_id is not None
    replace = args.get("replace") is True
    data, created = await run_state.start(ctx.board_id, ctx.source, goal, deliverables, replace)
    ctx.run_id = data["id"]
    if not created:
        return {
            "error": "RUN_ALREADY_OPEN",
            "message": f"A run is already open on this board ({data['status']}); you have "
            "joined it. Its goal and deliverables stand (set_goal with replace true pauses it "
            "and starts a new run).",
            "run_id": data["id"],
            "goal": data["goal"],
            "deliverables": data["deliverables"],
        }
    return {"run_id": data["id"], "goal": goal, "deliverables": deliverables}
