from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentRun, AgentStep


def open_run(session: Session, board_id: str) -> AgentRun | None:
    return session.scalar(
        select(AgentRun)
        .where(AgentRun.board_id == board_id, AgentRun.status.in_(("running", "needs_input")))
        .order_by(AgentRun.id.desc())
        .limit(1)
    )


def create_run(
    session: Session, board_id: str, source: str, goal: str, deliverables: list[str]
) -> AgentRun:
    run = AgentRun(board_id=board_id, source=source, goal=goal, deliverables_json=deliverables)
    session.add(run)
    session.flush()
    return run


def add_step(session: Session, run_id: str, **fields: Any) -> AgentStep:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise ValueError(f"unknown agent run {run_id}")
    last = session.scalar(select(func.max(AgentStep.turn)).where(AgentStep.run_id == run_id))
    fields.setdefault("args_json", {})
    fields.setdefault("item_ids_json", [])
    step = AgentStep(run_id=run_id, board_id=run.board_id, turn=(last or 0) + 1, **fields)
    session.add(step)
    session.flush()
    return step


def steps(session: Session, run_id: str) -> list[AgentStep]:
    return list(
        session.scalars(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.turn)
        )
    )


def runs(session: Session, board_id: str) -> list[AgentRun]:
    return list(
        session.scalars(
            select(AgentRun).where(AgentRun.board_id == board_id).order_by(AgentRun.id.desc())
        )
    )


def run_to_dict(r: AgentRun) -> dict[str, Any]:
    return {
        "id": r.id, "board_id": r.board_id, "source": r.source, "status": r.status,
        "goal": r.goal, "deliverables": r.deliverables_json, "output": r.output_json,
        "finish_refusals": r.finish_refusals, "note": r.note,
        "created_at": r.created_at, "updated_at": r.updated_at,
    }  # fmt: skip


def step_to_dict(s: AgentStep) -> dict[str, Any]:
    return {
        "id": s.id, "run_id": s.run_id, "turn": s.turn, "tool": s.tool, "args": s.args_json,
        "say": s.say, "ok": s.ok, "result": s.result_json, "item_ids": s.item_ids_json,
        "highlight": s.highlight, "created_at": s.created_at,
    }  # fmt: skip


def get_run(session: Session, run_id: str) -> AgentRun | None:
    return session.get(AgentRun, run_id)


def get_step(session: Session, step_id: str) -> AgentStep | None:
    return session.get(AgentStep, step_id)


def set_highlight(session: Session, step: AgentStep, highlight: bool) -> AgentStep:
    step.highlight = highlight
    session.flush()
    return step
