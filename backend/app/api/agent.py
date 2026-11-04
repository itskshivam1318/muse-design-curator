"""Read agent runs and their steps; pause an open run; toggle a step's highlight."""

from functools import partial
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import events
from app.api.boards import require_board
from app.api.deps import SessionDep
from app.db.repos import agent as agent_repo
from app.db.session import after_commit
from app.errors import AppError

router = APIRouter(prefix="/api")

OPEN = agent_repo.OPEN


class StepPatch(BaseModel):
    highlight: bool


class RunPatch(BaseModel):
    status: Literal["paused"]  # the person stops a run; only pausing is offered


@router.get("/boards/{board_id}/agent-runs")
def list_runs(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_board(session, board_id)
    return {"runs": [agent_repo.run_to_dict(r) for r in agent_repo.runs(session, board_id)]}


@router.get("/agent-runs/{run_id}")
def get_run(run_id: str, session: SessionDep) -> dict[str, Any]:
    run = agent_repo.get_run(session, run_id)
    if run is None:
        raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
    steps = [agent_repo.step_to_dict(s) for s in agent_repo.steps(session, run_id)]
    return {**agent_repo.run_to_dict(run), "steps": steps}


@router.patch("/agent-runs/{run_id}")
def patch_run(run_id: str, body: RunPatch, session: SessionDep) -> dict[str, Any]:
    run = agent_repo.get_run(session, run_id)
    if run is None:
        raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
    if run.status not in (*OPEN, body.status):  # pausing a paused run changes nothing
        raise AppError(409, "RUN_NOT_OPEN", f"The run is {run.status}; only an open run pauses")
    run.status = body.status
    session.flush()
    data = agent_repo.run_to_dict(run)
    after_commit(session, partial(events.publish, run.board_id, "agent.run", data))
    return data


@router.patch("/agent-steps/{step_id}")
def patch_step(step_id: str, body: StepPatch, session: SessionDep) -> dict[str, Any]:
    step = agent_repo.get_step(session, step_id)
    if step is None:
        raise AppError(404, "STEP_NOT_FOUND", "Agent step not found")
    agent_repo.set_highlight(session, step, body.highlight)
    data = agent_repo.step_to_dict(step)
    after_commit(session, partial(events.publish, step.board_id, "agent.step", data))
    return data
