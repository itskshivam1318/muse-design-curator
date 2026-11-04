"""Read agent runs and their steps; pause an open run; toggle a step's highlight; the board
chat (send a message, read the thread, start a new chat, read a run's trace)."""

from functools import partial
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import events
from app.agent import run_state
from app.agent.chat import runner
from app.agent.chat.trace import trace_path
from app.api.boards import require_board
from app.api.deps import SessionDep, new_session
from app.config import get_settings
from app.db.repos import agent as agent_repo
from app.db.session import after_commit
from app.errors import AppError

router = APIRouter(prefix="/api")

OPEN = agent_repo.OPEN
NO_OPEN_QUESTION = "That question is no longer open."


class StepPatch(BaseModel):
    highlight: bool


class RunPatch(BaseModel):
    status: Literal["paused"]  # the person stops a run; only pausing is offered


class Answer(BaseModel):
    call_id: str
    text: str | None = None
    choice: str | None = None
    box: list[float] | None = None


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    selection: list[str] = []
    answer: Answer | None = None


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
    """Pause an open run. A chat (`muse`) run's turn in flight is stopped and the run waits for
    the next message instead (it stays the board's chat); an MCP run is set `paused`."""
    run = agent_repo.get_run(session, run_id)
    if run is None:
        raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
    if run.status not in (*OPEN, body.status):  # pausing a paused run changes nothing
        raise AppError(409, "RUN_NOT_OPEN", f"The run is {run.status}; only an open run pauses")
    if run.source == "muse":
        runner.stop(run.id)
        run.status = "waiting" if run.status in OPEN else run.status
    else:
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


# --- the board chat ------------------------------------------------------------------------


def _check_board(board_id: str) -> None:
    with new_session() as session:
        require_board(session, board_id)


def _add_person_message(
    board_id: str, run_id: str, body: ChatMessage
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """Save the person's message on the run, and the question it answers (now answered, in the
    same transaction: a second answer finds no open question); None when its answer matches no
    open question."""
    with agent_repo.WRITE_LOCK, new_session() as session:
        question = agent_repo.open_question(session, run_id)
        call_id = (question.data_json or {}).get("call_id") if question is not None else None
        answer = body.answer.model_dump(exclude_none=True) if body.answer is not None else None
        if answer is not None and (call_id is None or answer["call_id"] != call_id):
            return None
        if answer is None and call_id is not None:
            answer = {"call_id": call_id, "text": body.text}
        data: dict[str, Any] = {}
        if body.selection:
            data["selection"] = body.selection
        if answer is not None:
            data["answer"] = answer
        answered = question if answer is not None else None  # an answer has an open question
        if answered is not None:
            answered.answered = True
        m = agent_repo.add_message(session, run_id, board_id, "person", body.text, data or None)
        session.commit()
        return (
            agent_repo.message_to_dict(m),
            agent_repo.message_to_dict(answered) if answered is not None else None,
        )


def _run_dict(run_id: str) -> dict[str, Any]:
    with new_session() as session:
        run = agent_repo.get_run(session, run_id)
        if run is None:
            raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
        return agent_repo.run_to_dict(run)


@router.post("/boards/{board_id}/agent/messages", status_code=202)
async def post_message(board_id: str, body: ChatMessage) -> dict[str, Any]:
    """Send the person's message to the board's chat. The first message opens a chat run (its
    goal is the message); later ones join it. The run then works in the background (inline under
    JOBS_SYNC). `answer` answers the open question; plain text sent while a question is open is
    taken as its answer `{call_id: <the open question's>, text}`. An answer closes the question
    at once (`agent.question` with `answered: true`).

    Refusals (409): CHAT_UNAVAILABLE (demo mode, or no chat model; the message says which),
    MCP_RUN_OPEN (Claude Code is working on the board), NO_OPEN_QUESTION (an `answer` whose
    `call_id` matches no open question)."""
    await run_in_threadpool(_check_board, board_id)
    reason = runner.unavailable()
    if reason is not None:
        raise AppError(409, "CHAT_UNAVAILABLE", reason)
    if body.answer is not None and await run_state.current(board_id, None, "muse") is None:
        raise AppError(409, "NO_OPEN_QUESTION", NO_OPEN_QUESTION)  # and no chat to open for it
    run, _created = await run_state.start(board_id, "muse", body.text[:1000], [])
    if "error" in run:
        raise AppError(409, run["error"], run["message"])
    saved = await run_in_threadpool(_add_person_message, board_id, run["id"], body)
    if saved is None:
        raise AppError(409, "NO_OPEN_QUESTION", NO_OPEN_QUESTION)
    message, answered = saved
    if answered is not None:
        events.publish(board_id, "agent.question", answered)
    events.publish(board_id, "agent.message", message)
    if get_settings().JOBS_SYNC:
        await runner.kick_sync(board_id, run["id"])
    else:
        runner.kick(board_id, run["id"])
    return {"run": await run_in_threadpool(_run_dict, run["id"]), "message": message}


@router.get("/agent-runs/{run_id}/messages")
def list_messages(run_id: str, session: SessionDep) -> dict[str, Any]:
    if agent_repo.get_run(session, run_id) is None:
        raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
    return {
        "messages": [agent_repo.message_to_dict(m) for m in agent_repo.messages(session, run_id)]
    }


@router.post("/agent-runs/{run_id}/new-chat")
def new_chat(run_id: str, session: SessionDep) -> dict[str, Any]:
    """End the chat run (`done`), stopping its turn in flight; the next message opens a new one."""
    run = agent_repo.get_run(session, run_id)
    if run is None:
        raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
    if run.source != "muse":
        raise AppError(409, "NOT_A_CHAT", "Only a chat run is ended by New chat")
    runner.stop(run.id)
    if run.status != "done":
        run.status = "done"
        session.flush()
        after_commit(session, partial(events.publish, run.board_id, "agent.run",
                                      agent_repo.run_to_dict(run)))  # fmt: skip
    return agent_repo.run_to_dict(run)


@router.get("/agent-runs/{run_id}/trace", response_class=PlainTextResponse)
def get_trace(run_id: str, session: SessionDep) -> PlainTextResponse:
    """The run's JSONL trace (one record per line)."""
    if agent_repo.get_run(session, run_id) is None:
        raise AppError(404, "RUN_NOT_FOUND", "Agent run not found")
    path = trace_path(run_id)
    if not get_settings().AGENT_TRACES or not path.is_file():
        raise AppError(404, "TRACE_NOT_FOUND", "No trace for this run")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@router.get("/agent/chat-status")
def chat_status() -> dict[str, Any]:
    """Whether the board chat can run here, and why not."""
    reason = runner.unavailable()
    return {"available": reason is None, "reason": reason}
