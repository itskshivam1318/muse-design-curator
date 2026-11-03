"""Reading and changing the board's agent run (its own session, committed), announcing each change
as `agent.run` on the board's event feed. The run table is the agent's own, so tools write it
here directly; board changes still go through the API."""

from typing import Any

from starlette.concurrency import run_in_threadpool

from app import events
from app.api.deps import new_session
from app.db.models import AgentRun
from app.db.repos import agent as agent_repo

OPEN = ("running", "needs_input")


def _start(
    board_id: str, source: str, goal: str, deliverables: list[str], replace: bool
) -> tuple[dict[str, Any], bool]:
    paused: dict[str, Any] | None = None
    with agent_repo.WRITE_LOCK, new_session() as session:
        existing = agent_repo.open_run(session, board_id)
        if existing is not None and not replace:
            return agent_repo.run_to_dict(existing), False
        if existing is not None:
            existing.status = "paused"
            session.flush()
            paused = agent_repo.run_to_dict(existing)
        run = agent_repo.create_run(session, board_id, source, goal, deliverables)
        session.commit()
        data = agent_repo.run_to_dict(run)
    if paused is not None:
        events.publish(board_id, "agent.run", paused)
    events.publish(board_id, "agent.run", data)
    return data, True


async def start(
    board_id: str, source: str, goal: str, deliverables: list[str], replace: bool = False
) -> tuple[dict[str, Any], bool]:
    """A new run on the board, or the one already open there; `True` when it was created.
    With `replace`, an open run is paused and a new one started in its place."""
    return await run_in_threadpool(_start, board_id, source, goal, deliverables, replace)


def _current(board_id: str, run_id: str | None) -> dict[str, Any] | None:
    with new_session() as session:
        run = session.get(AgentRun, run_id) if run_id else None
        if run is None or run.board_id != board_id or run.status not in OPEN:
            run = agent_repo.open_run(session, board_id)
        return agent_repo.run_to_dict(run) if run is not None else None


async def current(board_id: str, run_id: str | None) -> dict[str, Any] | None:
    """The open run: `run_id`'s if it is open on the board, else the board's open run."""
    return await run_in_threadpool(_current, board_id, run_id)


def _update(run_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    with new_session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"unknown agent run {run_id}")
        for key, value in fields.items():
            setattr(run, key, value)
        session.commit()
        data = agent_repo.run_to_dict(run)
    events.publish(data["board_id"], "agent.run", data)
    return data


async def update(run_id: str, **fields: Any) -> dict[str, Any]:
    """Set the run's columns, commit, publish `agent.run`; the run as `run_to_dict`."""
    return await run_in_threadpool(_update, run_id, fields)


def no_run() -> dict[str, Any]:
    return {"error": "NO_RUN", "message": "There is no open run on this board: set_goal first."}
