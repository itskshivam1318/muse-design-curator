"""Runs the board chat: one driver per board, taking turns while the person has messages waiting.

`kick` is called after a person message is saved. A board with a driver already going only
notes the kick (the driver hands new messages to the turn in flight, or runs another turn after
it); otherwise a driver starts as a task (`kick_sync` awaits it inline, for JOBS_SYNC). One turn
runs per board at a time. `stop` asks the turn in flight to stop calling tools.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import events
from app.agent.chat.loop import run_turn
from app.agent.chat.model import get_chat_model
from app.api.deps import new_session
from app.config import get_settings
from app.db.models import AgentRun
from app.db.repos import agent as agent_repo

__all__ = ["FAILED_TEXT", "kick", "kick_sync", "reset_running_on_startup", "stop", "unavailable"]

log = logging.getLogger(__name__)

FAILED_TEXT = "Something went wrong. Send a message to try again."
DEMO_OFF = "Chat is off in the demo."
NO_MODEL = "Chat needs Muse Spark (REASONING_PROVIDER=muse-spark)."


@dataclass
class _Board:
    run_id: str
    active: bool = False  # a driver is going (as a task, or inline)
    kicked: bool = False  # a message arrived since the driver last looked
    task: asyncio.Task[None] | None = field(default=None, repr=False)


_boards: dict[str, _Board] = {}
_stopped: set[str] = set()  # run ids whose turn in flight should stop


def unavailable() -> str | None:
    """Why the chat cannot run here, or None when it can."""
    settings = get_settings()
    if settings.DEMO_MODE:
        return DEMO_OFF
    if get_chat_model(settings) is None:
        return NO_MODEL
    return None


def _note(board_id: str, run_id: str) -> _Board:
    state = _boards.get(board_id)
    if state is None:
        state = _boards[board_id] = _Board(run_id)
    state.run_id = run_id
    state.kicked = True
    return state


def kick(board_id: str, run_id: str) -> None:
    """Run the chat on `run_id` in the background unless the board's driver is already going."""
    state = _note(board_id, run_id)
    if state.active:
        return
    state.active = True
    state.task = asyncio.create_task(_drive(board_id, state))


async def kick_sync(board_id: str, run_id: str) -> None:
    """`kick`, awaiting the driver inline (JOBS_SYNC)."""
    state = _note(board_id, run_id)
    if state.active:
        return
    state.active = True
    await _drive(board_id, state)


def stop(run_id: str) -> None:
    """Ask the run's turn in flight to stop; messages sent before the stop wait for the next."""
    _stopped.add(run_id)
    for state in _boards.values():
        if state.run_id == run_id:
            state.kicked = False


# --- the driver ------------------------------------------------------------------------------


def _pending(run_id: str) -> list[dict[str, Any]]:
    """The run's unconsumed person messages, or none when the run is no longer open."""
    with new_session() as session:
        run = agent_repo.get_run(session, run_id)
        if run is None or run.status not in agent_repo.OPEN:
            return []
        return [
            agent_repo.message_to_dict(m) for m in agent_repo.unconsumed_messages(session, run_id)
        ]


def _fail(run_id: str, board_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """An open run goes to `waiting` with the failure message; None when it is not open (e.g.
    ended by New chat meanwhile)."""
    with new_session() as session:
        run = agent_repo.get_run(session, run_id)
        if run is None or run.status not in agent_repo.OPEN:
            return None
        run.status = "waiting"
        m = agent_repo.add_message(session, run_id, board_id, "agent", FAILED_TEXT)
        session.commit()
        return agent_repo.run_to_dict(run), agent_repo.message_to_dict(m)


async def _turn(board_id: str, run_id: str) -> bool:
    """One turn on the run; False when it failed (the run is then left `waiting`, with a
    message), or there is no chat model."""
    model = get_chat_model(get_settings())
    if model is None:
        return False
    handed: set[str] = set()

    def next_message() -> dict[str, Any] | None:
        # messages are handed over once each; the turn itself skips any it took in at its start
        for m in _pending(run_id):
            if m["id"] not in handed:
                handed.add(m["id"])
                return m
        return None

    try:
        await run_turn(
            board_id, run_id, model, should_stop=lambda: run_id in _stopped,
            next_message=next_message,
        )  # fmt: skip
        return True
    except Exception:
        log.exception("chat turn crashed on run %s", run_id)
        try:
            failed = await run_in_threadpool(_fail, run_id, board_id)
            if failed is not None:
                events.publish(board_id, "agent.run", failed[0])
                events.publish(board_id, "agent.message", failed[1])
        except Exception:
            log.exception("could not mark chat run %s waiting", run_id)
        return False


async def _drive(board_id: str, state: _Board) -> None:
    try:
        while True:
            run_id = state.run_id
            state.kicked = False
            _stopped.discard(run_id)  # a stop is for the turn in flight, not the next one
            ok = await _turn(board_id, run_id)
            if run_id in _stopped or not ok:
                # stopped or failed: go on only for a message sent since
                _stopped.discard(run_id)
                if not state.kicked:
                    return
            while True:  # anything left? look again if a kick lands while looking
                state.kicked = False
                if state.run_id != run_id:
                    break
                if await run_in_threadpool(_pending, run_id):
                    break
                if not state.kicked:
                    return
    finally:
        state.active = False
        state.task = None


# --- startup ---------------------------------------------------------------------------------


def reset_running_on_startup() -> int:
    """Chat runs left `running` by a previous process go to `waiting` (their turns are gone);
    the number reset."""
    with new_session() as session:
        runs = list(
            session.scalars(
                select(AgentRun).where(AgentRun.source == "muse", AgentRun.status == "running")
            )
        )
        for run in runs:
            run.status = "waiting"
        session.commit()
        return len(runs)
