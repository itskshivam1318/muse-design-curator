"""Recording a tool call as an AgentStep and putting it on the board's event feed."""

import json
from typing import Any

from starlette.concurrency import run_in_threadpool

from app import events
from app.api.deps import new_session
from app.db.repos import agent as agent_repo

RESULT_CAP = 4096  # bytes of JSON kept on a step; the caller still gets the full result
_VALUE_CAP = 200  # chars of an over-long top-level value kept in a truncated summary


def summarise(result: dict[str, Any]) -> dict[str, Any]:
    """The result as stored on a step: as-is when it fits in RESULT_CAP, else shortened."""
    plain: dict[str, Any] = json.loads(json.dumps(result, default=str))
    if _size(plain) <= RESULT_CAP:
        return plain
    short: dict[str, Any] = {}
    for key, value in plain.items():
        encoded = json.dumps(value)
        short[key] = value if len(encoded) <= _VALUE_CAP else encoded[:_VALUE_CAP] + "…"
    short["truncated"] = True
    if _size(short) <= RESULT_CAP:
        return short
    return {"truncated": True, "keys": list(plain)[:50]}


def _size(value: Any) -> int:
    return len(json.dumps(value).encode())


def _record(
    run_id: str,
    tool: str,
    args: dict[str, Any],
    say: str | None,
    highlight: bool,
    result: dict[str, Any],
) -> None:
    item_ids = result.get("item_ids")
    with new_session() as session:
        step = agent_repo.add_step(
            session,
            run_id,
            tool=tool,
            args_json=json.loads(json.dumps(args, default=str)),
            say=say,
            ok="error" not in result,
            result_json=summarise(result),
            item_ids_json=[str(i) for i in item_ids] if isinstance(item_ids, list) else [],
            highlight=highlight,
        )
        session.commit()
        board_id, data = step.board_id, agent_repo.step_to_dict(step)
    events.publish(board_id, "agent.step", data)


async def record(
    run_id: str,
    tool: str,
    args: dict[str, Any],
    say: str | None,
    highlight: bool,
    result: dict[str, Any],
) -> None:
    """Store the step (its own session, committed) then publish `agent.step` for the board."""
    await run_in_threadpool(_record, run_id, tool, args, say, highlight, result)
