"""The board chat loop: one turn of the conversation, from the person's messages to a reply,
a question, or a stop.

The run's history (Responses input items) lives on `agent_runs.history_json`. A person message
is *consumed* once it is in that history: `data["consumed"]` is set on the message when the
history holding it is saved, so a turn that dies before saving leaves its messages for the next.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from app import events
from app.agent import run_state, tools
from app.agent.chat import local_tools
from app.agent.chat.history import compact
from app.agent.chat.model import ChatModel, ModelError, ToolCall
from app.agent.chat.prompt import CHAT_HIDDEN, SYSTEM
from app.agent.chat.trace import Trace
from app.agent.context import ApiClient, ToolContext, api_error
from app.api.deps import new_session
from app.config import data_dir, get_settings
from app.db.models import AgentMessage
from app.db.repos import agent as agent_repo

__all__ = ["MAX_STEPS", "offered_tools", "run_turn"]

log = logging.getLogger(__name__)

MAX_STEPS = 40
STEP_CAP_TEXT = f"I stopped after {MAX_STEPS} steps. Tell me how to continue."
NOT_AVAILABLE = {"error": "NOT_AVAILABLE", "message": "That tool is not offered in this chat."}
BAD_ARGUMENTS = {"error": "BAD_ARGUMENTS", "message": "The arguments could not be used."}
SKIPPED = {
    "error": "SKIPPED",
    "message": "Not run: the turn waited for the person's answer. Call it again if still needed.",
}
STOPPED = {"error": "STOPPED", "message": "Not run: the person stopped the work."}
SUPERSEDED = {
    "error": "SUPERSEDED",
    "message": "The person sent a message first; read it and ask again if needed.",
}
TURN_FAILED = {"error": "TOOL_FAILED", "message": "Not run: the turn failed."}
_CALL_TYPES = ("function_call", "function_call_output")


def offered_tools() -> list[dict[str, Any]]:
    """The tools a chat run is offered: the registry's for "muse", less CHAT_HIDDEN, plus the
    chat-only ones."""
    shared = [d for d in tools.definitions("muse") if d["name"] not in CHAT_HIDDEN]
    return shared + local_tools.DEFINITIONS


# --- database work (in the threadpool) -------------------------------------------------------


def _load(run_id: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """The run's status, history and unconsumed person messages."""
    with new_session() as session:
        run = agent_repo.get_run(session, run_id)
        if run is None:
            raise ValueError(f"unknown agent run {run_id}")
        return (
            run.status,
            list(run.history_json or []),
            [
                agent_repo.message_to_dict(m)
                for m in agent_repo.unconsumed_messages(session, run_id)
            ],
        )


def _settle(run_id: str, consumed: list[str]) -> str:
    """Mark the messages taken into the history; the run's status. (The route marks a question
    answered when its answer arrives.)"""
    with new_session() as session:
        for message_id in consumed:
            m = session.get(AgentMessage, message_id)
            if m is not None:
                agent_repo.mark_consumed(session, m)
        session.commit()
        run = agent_repo.get_run(session, run_id)
        return run.status if run is not None else "done"


def _add_message(
    run_id: str, board_id: str, role: str, text: str, data: dict[str, Any] | None
) -> dict[str, Any]:
    with new_session() as session:
        m = agent_repo.add_message(session, run_id, board_id, role, text, data)
        session.commit()
        return agent_repo.message_to_dict(m)


async def _post(
    board_id: str, run_id: str, role: str, text: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Add a message to the thread and announce it (`agent.question` for a question, else
    `agent.message`)."""
    message = await run_in_threadpool(_add_message, run_id, board_id, role, text, data)
    events.publish(board_id, "agent.question" if role == "question" else "agent.message", message)
    return message


# --- history items ---------------------------------------------------------------------------


def _person_item(board_id: str, message: dict[str, Any], first: bool) -> dict[str, Any]:
    lines = [f"[Board {board_id} is open.]"] if first else []
    lines.append(message["text"])
    selection = (message.get("data") or {}).get("selection")
    if selection:
        lines.append("Selected on the board: " + ", ".join(str(i) for i in selection))
    return {
        "role": "user",
        "content": [{"type": "input_text", "text": "\n".join(lines)}],
        "muse_person": True,
    }


def _output(call_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result, default=str),
    }


def _answer(message: dict[str, Any]) -> dict[str, Any]:
    """The person's answer to a question, as that call's output."""
    data = message.get("data") or {}
    answer = data.get("answer") or {}
    if answer.get("box") is not None:
        return {"box": answer["box"]}
    if answer.get("choice") is not None:
        return {"choice": answer["choice"]}
    out: dict[str, Any] = {"answer": answer.get("text") or message["text"]}
    if data.get("selection"):
        out["selection"] = data["selection"]
    return out


def _answer_call(message: dict[str, Any]) -> str | None:
    """The call a person message answers, if it is an answer."""
    return ((message.get("data") or {}).get("answer") or {}).get("call_id")


def _open_calls(history: list[dict[str, Any]]) -> set[str]:
    """The calls in the history still without an output: a suspended turn's question."""
    done = {it.get("call_id") for it in history if it.get("type") == "function_call_output"}
    return {
        str(it["call_id"])
        for it in history
        if it.get("type") == "function_call" and it.get("call_id") not in done
    }


def _insert_output(history: list[dict[str, Any]], item: dict[str, Any]) -> None:
    """Put a late call output among its turn's calls and outputs, ahead of anything after them
    (such as `look_at` pictures), so calls stay next to their outputs."""
    at = next(
        (
            i
            for i, it in enumerate(history)
            if it.get("type") == "function_call" and it.get("call_id") == item["call_id"]
        ),
        None,
    )
    if at is None:
        history.append(item)
        return
    at += 1
    while at < len(history) and history[at].get("type") in _CALL_TYPES:
        at += 1
    history.insert(at, item)


def _close_calls(history: list[dict[str, Any]]) -> None:
    """Give every call still without an output a failure output, so the saved history stays
    one the model accepts after a turn broke off."""
    answered = {it.get("call_id") for it in history if it.get("type") == "function_call_output"}
    for it in list(history):
        if it.get("type") == "function_call" and it.get("call_id") not in answered:
            _insert_output(history, _output(it["call_id"], TURN_FAILED))


# --- the turn --------------------------------------------------------------------------------


class _Turn:
    def __init__(
        self, board_id: str, run_id: str, model: ChatModel, api: ApiClient,
        should_stop: Callable[[], bool], next_message: Callable[[], dict[str, Any] | None],
    ) -> None:  # fmt: skip
        self.board_id = board_id
        self.run_id = run_id
        self.model = model
        self.ctx = ToolContext(api, board_id, run_id, source="muse")
        self.should_stop = should_stop
        self.next_message = next_message
        self.trace = Trace(run_id, data_dir(get_settings()))
        self.tools = offered_tools()
        self.names = {t["name"] for t in self.tools}
        self.history: list[dict[str, Any]] = []
        self.consumed: list[str] = []
        self.stopped = False  # a stop came between two calls of one model turn

    def take_person(self, message: dict[str, Any]) -> None:
        """Add a person message to the history, once: `next_message` may hand back one the turn
        already took in at its start."""
        if message["id"] in self.consumed:
            return
        first = not self.history
        self.history.append(_person_item(self.board_id, message, first))
        self.consumed.append(message["id"])
        self.trace.message("person", message["text"])

    async def finish(self, status: str) -> str:
        """Save the history; the run goes to `status` unless it was ended meanwhile."""
        now = await run_in_threadpool(_settle, self.run_id, self.consumed)
        if now not in agent_repo.OPEN:  # ended (New chat) while we worked: keep it ended
            await run_state.update(self.run_id, history_json=self.history)
            return now
        await run_state.update(self.run_id, status=status, history_json=self.history)
        return status

    async def say(self, text: str) -> None:
        await _post(self.board_id, self.run_id, "agent", text)
        self.trace.message("agent", text)

    async def run(self) -> str:
        """The turn; anything unexpected after the history is loaded ends it as `waiting` with a
        message, the history saved, rather than leaving the run `running`."""
        status, self.history, pending = await run_in_threadpool(_load, self.run_id)
        try:
            return await self.work(status, pending)
        except Exception as e:
            log.exception("chat turn failed on run %s", self.run_id)
            _close_calls(self.history)
            await self.say(
                f"Something went wrong ({type(e).__name__}). Send a message to try again."
            )
            return await self.finish("waiting")

    def take_pending(self, pending: list[dict[str, Any]]) -> None:
        """Take the person's messages in: an answer becomes the output of the call it names
        (the one the turn suspended on); the rest are person messages. A suspended call left
        unanswered is superseded: the person wrote on instead."""
        open_calls = _open_calls(self.history)
        for message in pending:
            call_id = _answer_call(message)
            if call_id is not None and call_id in open_calls:
                _insert_output(self.history, _output(call_id, _answer(message)))
                open_calls.discard(call_id)
                self.consumed.append(message["id"])
                self.trace.message("person", message["text"])
            else:
                self.take_person(message)
        for call_id in sorted(open_calls):
            _insert_output(self.history, _output(call_id, SUPERSEDED))

    async def work(self, status: str, pending: list[dict[str, Any]]) -> str:
        sent = len(self.history)  # the trace's new items start here: older ones were traced before
        if status not in agent_repo.OPEN:
            return status
        if not pending and _open_calls(self.history):
            return status  # still waiting for the answer
        self.take_pending(pending)
        await run_state.update(self.run_id, status="running")

        for step in range(MAX_STEPS):
            if self.should_stop():
                return await self.finish("waiting")
            request = compact(self.history)
            try:
                turn = await run_in_threadpool(self.model.respond, SYSTEM, request, self.tools)
            except ModelError as e:
                await self.say(f"Muse Spark failed ({e.code}). Send a message to try again.")
                return await self.finish("waiting")
            person_turns = sum(1 for it in self.history if it.get("muse_person"))
            self.trace.model_call(person_turns, step, len(request), self.history[sent:], turn)
            self.history.extend(turn.output)
            sent = len(self.history)

            if not turn.calls:
                await self.say(turn.text)
                return await self.finish("waiting")

            asked = await self.run_calls(turn.calls)
            if asked is not None:
                text, data = asked
                await _post(self.board_id, self.run_id, "question", text, data)
                self.trace.message("question", text)
                return await self.finish("needs_input")
            if self.stopped:
                return await self.finish("waiting")
            while (arrived := self.next_message()) is not None:
                self.take_person(arrived)

        await self.say(STEP_CAP_TEXT)
        return await self.finish("waiting")

    async def run_calls(self, calls: list[ToolCall]) -> tuple[str, dict[str, Any]] | None:
        """Run one model turn's calls, adding their outputs (then any pictures) to the history.
        Returns the question to ask when a call suspends the turn; the calls after it are
        skipped. A stop skips the calls not yet run."""
        asked: tuple[str, dict[str, Any]] | None = None
        pictures: list[dict[str, Any]] = []
        for c in calls:
            if asked is not None:
                self.history.append(_output(c.call_id, SKIPPED))
                continue
            if self.stopped or self.should_stop():
                self.stopped = True
                self.history.append(_output(c.call_id, STOPPED))
                continue
            try:
                if c.name in local_tools.SUSPENDING and local_tools.valid_args(c.name, c.arguments):
                    question = await self.question(c)
                    if isinstance(question, tuple):
                        asked = question
                        continue
                    result = question
                else:
                    result = await self.call(c, pictures)
            except (
                Exception
            ) as e:  # a chat-only tool's API call failed (registry tools never raise)
                log.exception("chat tool %s failed", c.name)
                result = {"error": "TOOL_FAILED", "message": str(e) or type(e).__name__}
            self.history.append(_output(c.call_id, result))
        self.history.extend(pictures)
        return asked

    async def question(self, c: ToolCall) -> tuple[str, dict[str, Any]] | dict[str, Any]:
        """The question's text and data, or an error for the model (the part cannot be shown)."""
        data: dict[str, Any] = {"call_id": c.call_id, "tool": c.name, "args": c.arguments}
        if c.name == "ask_user":
            return str(c.arguments["question"]), data
        item_id, part = c.arguments["item_id"], c.arguments["part"]
        status, body = await self.ctx.api.get(f"/api/items/{item_id}/parts/{part}/region")
        if status != 200:
            return api_error(status, body)
        data["region"] = body
        return str(c.arguments["why"]), data

    async def call(self, c: ToolCall, pictures: list[dict[str, Any]]) -> dict[str, Any]:
        if c.name not in self.names:
            return dict(NOT_AVAILABLE)
        if c.arguments.get("_bad_arguments"):
            return dict(BAD_ARGUMENTS)
        if c.name in local_tools.NAMES:
            if not local_tools.valid_args(c.name, c.arguments):
                return dict(BAD_ARGUMENTS)
            return await self.look_at(c.arguments["item_ids"], pictures)
        started = time.monotonic()
        result = await tools.run_tool(self.ctx, c.name, c.arguments)
        self.trace.tool(c.name, c.arguments, result, time.monotonic() - started)
        return result

    async def look_at(self, item_ids: list[str], pictures: list[dict[str, Any]]) -> dict[str, Any]:
        item, missing = await local_tools.look_at_images(self.ctx.api, item_ids)
        if item is None:
            return {"error": "NO_PICTURES", "message": "None of those pictures could be read.",
                    "missing": missing}  # fmt: skip
        pictures.append(item)
        return {"ok": True, "missing": missing} if missing else {"ok": True}


async def run_turn(
    board_id: str,
    run_id: str,
    model: ChatModel,
    api: ApiClient | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    next_message: Callable[[], dict[str, Any] | None] = lambda: None,
) -> str:
    """Run the chat until the agent replies, asks, is stopped, or hits MAX_STEPS.

    Takes the run's unconsumed person messages into its history (an answer as the output of the
    call it names), then alternates model calls and tool calls. `should_stop` is checked before every
    model call and tool call; `next_message` is drained after each round of calls for messages
    the person sent meanwhile. Returns the run's status after the turn: `"waiting"` or
    `"needs_input"` (or the run's own status if it was not open, or was ended meanwhile).
    """
    owned = api is None
    client = api if api is not None else ApiClient()
    try:
        return await _Turn(board_id, run_id, model, client, should_stop, next_message).run()
    finally:
        if owned:
            await client.aclose()
