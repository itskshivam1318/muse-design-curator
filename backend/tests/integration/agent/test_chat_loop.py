"""The board chat loop: a scripted model drives run_turn over the test app."""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import jobs
from app.agent import run_state
from app.agent.chat import loop
from app.agent.chat.model import FakeChatModel, ModelError, ModelTurn, ToolCall
from app.agent.chat.trace import trace_path
from app.agent.context import ApiClient
from app.api import deps
from app.board import profile_hook
from app.db.models import ItemPart
from app.db.repos import agent as agent_repo
from app.db.repos import items as items_repo
from app.storage import files
from tests.media import image_bytes


@pytest.fixture(autouse=True)
def env(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)
    monkeypatch.setattr(jobs, "enqueue", lambda _name, **_kw: None)
    yield


@pytest.fixture
async def api(client: TestClient) -> Any:
    a = ApiClient()
    yield a
    await a.aclose()


@pytest.fixture
async def run_id(board: str) -> str:
    run, created = await run_state.start(board, "muse", "chat", [])
    assert created
    return str(run["id"])


@pytest.fixture
def item_id(client: TestClient, board: str) -> str:
    data = image_bytes(seed=3)
    sha = files.sha256_hex(data)
    with deps.new_session() as s:
        item = items_repo.create(
            s, board_id=board, kind="image", origin="upload", sha256=sha,
            storage_path=files.save_original(data, sha, "png"),
            thumb_path=files.save_thumb(Image.open(io.BytesIO(data)), sha),
            parse_status="completed", x=0, y=0, w=320, h=240,
        )  # fmt: skip
        s.add(ItemPart(item_id=item.id, key="body", label="Body", region_kind="mask", source="ai"))
        s.commit()
        return item.id


# --- helpers ---------------------------------------------------------------------------------


def say(board: str, run_id: str, text: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    with deps.new_session() as s:
        m = agent_repo.add_message(s, run_id, board, "person", text, data)
        s.commit()
        return agent_repo.message_to_dict(m)


def thread(run_id: str) -> list[dict[str, Any]]:
    with deps.new_session() as s:
        return [agent_repo.message_to_dict(m) for m in agent_repo.messages(s, run_id)]


def steps(run_id: str) -> list[dict[str, Any]]:
    with deps.new_session() as s:
        return [agent_repo.step_to_dict(m) for m in agent_repo.steps(s, run_id)]


def run_row(run_id: str) -> tuple[str, list[dict[str, Any]]]:
    with deps.new_session() as s:
        run = agent_repo.get_run(s, run_id)
        assert run is not None
        return run.status, run.history_json or []


def reply(text: str) -> ModelTurn:
    out = [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}]  # fmt: skip
    return ModelTurn(out, text, [], {}, 0.0)


def calls(*specs: tuple[str, dict[str, Any], str]) -> ModelTurn:
    out = [
        {"type": "function_call", "name": n, "arguments": json.dumps(a), "call_id": c}
        for n, a, c in specs
    ]
    return ModelTurn(out, "", [ToolCall(n, a, c) for n, a, c in specs], {}, 0.0)


def call(name: str, args: dict[str, Any], call_id: str = "call_1") -> ModelTurn:
    return calls((name, args, call_id))


def outputs(items: list[dict[str, Any]]) -> dict[str, Any]:
    """call_id → parsed function_call_output."""
    return {
        i["call_id"]: json.loads(i["output"])
        for i in items
        if i.get("type") == "function_call_output"
    }


def input_text(items: list[dict[str, Any]]) -> str:
    texts = []
    for i in items:
        content = i.get("content")
        if isinstance(content, list):
            texts += [p.get("text", "") for p in content if isinstance(p, dict)]
    return "\n".join(texts)


# --- tests -----------------------------------------------------------------------------------


async def test_reply_without_tools_posts_agent_message(
    board: str, run_id: str, api: ApiClient
) -> None:
    say(board, run_id, "hello")
    model = FakeChatModel([reply("Hi. Tell me what to change.")])
    assert await loop.run_turn(board, run_id, model, api) == "waiting"

    msgs = thread(run_id)
    assert [m["role"] for m in msgs] == ["person", "agent"]
    assert msgs[1]["text"] == "Hi. Tell me what to change."
    assert msgs[0]["data"] == {"consumed": True}
    first = model.calls[0][1]
    assert first[0]["role"] == "user" and "muse_person" not in first[0]
    assert input_text(first).startswith(f"[Board {board} is open.]")
    assert "hello" in input_text(first)
    status, history = run_row(run_id)
    assert status == "waiting" and history[0]["muse_person"] is True
    assert history[-1]["type"] == "message"
    records = [json.loads(line) for line in trace_path(run_id).read_text().splitlines()]
    [model_call] = [r for r in records if r["kind"] == "model_call"]
    assert model_call["new_items"][0]["muse_person"] is True  # the turn's new input is traced


async def test_tool_call_runs_registry_and_records_step(
    board: str, run_id: str, api: ApiClient
) -> None:
    say(board, run_id, "what is here?")
    model = FakeChatModel(
        [call("read_board", {"say": "Reading the board."}), reply("The board is empty.")]
    )
    assert await loop.run_turn(board, run_id, model, api) == "waiting"

    [step] = steps(run_id)
    assert step["tool"] == "read_board" and step["say"] == "Reading the board." and step["ok"]
    result = outputs(model.calls[1][1])["call_1"]
    assert result["board"]["id"] == board
    names = {t["name"] for t in model.calls[0][2]}
    assert {"read_board", "ask_user", "confirm_part", "look_at", "add_part"} <= names
    assert not names & {"finish", "set_goal", "create_board", "open_board"}


async def test_ask_user_suspends_and_answer_resumes(
    board: str, run_id: str, api: ApiClient
) -> None:
    say(board, run_id, "make it warmer")
    ask = ("ask_user", {"question": "Which one?", "choices": ["itm_a", "itm_b"]}, "call_q")
    model = FakeChatModel([calls(ask, ("read_board", {}, "call_late")), reply("Done with itm_a.")])
    assert await loop.run_turn(board, run_id, model, api) == "needs_input"

    question = thread(run_id)[-1]
    assert question["role"] == "question" and question["text"] == "Which one?"
    assert question["data"]["call_id"] == "call_q" and question["data"]["tool"] == "ask_user"
    assert question["data"]["args"]["choices"] == ["itm_a", "itm_b"]
    assert not question["answered"]
    status, history = run_row(run_id)
    assert status == "needs_input"
    assert outputs(history)["call_late"]["error"] == "SKIPPED"  # every call has an output
    assert steps(run_id) == []

    say(board, run_id, "the first", {"answer": {"call_id": "call_q", "text": "the first"}})
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    second = model.calls[1][1]
    assert outputs(second)["call_q"] == {"answer": "the first"}
    assert "the first" not in input_text(second)  # the answer is the call's output, not a message
    msgs = thread(run_id)
    assert next(m for m in msgs if m["role"] == "question")["answered"] is True
    assert msgs[-1]["role"] == "agent" and run_row(run_id)[0] == "waiting"


async def test_choice_answer_reaches_model(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "use that one")
    model = FakeChatModel(
        [call("ask_user", {"question": "Which?", "choices": ["itm_a"]}), reply("ok")]
    )
    await loop.run_turn(board, run_id, model, api)
    say(board, run_id, "itm_a", {"answer": {"call_id": "call_1", "choice": "itm_a"}})
    await loop.run_turn(board, run_id, model, api)
    assert outputs(model.calls[1][1])["call_1"] == {"choice": "itm_a"}


async def test_confirm_part_question_carries_region(
    board: str, run_id: str, api: ApiClient, item_id: str
) -> None:
    say(board, run_id, "change the body")
    args = {"item_id": item_id, "part": "body", "why": "Is this the body?"}
    model = FakeChatModel([call("confirm_part", args)])
    assert await loop.run_turn(board, run_id, model, api) == "needs_input"

    question = thread(run_id)[-1]
    assert question["role"] == "question" and question["text"] == "Is this the body?"
    assert question["data"]["tool"] == "confirm_part" and question["data"]["args"] == args
    assert question["data"]["region"]["kind"] == "mask"


async def test_confirm_part_unknown_part_goes_back_to_model(
    board: str, run_id: str, api: ApiClient, item_id: str
) -> None:
    say(board, run_id, "change the roof")
    args = {"item_id": item_id, "part": "roof", "why": "Is this the roof?"}
    model = FakeChatModel([call("confirm_part", args), reply("There is no roof part.")])
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    assert "error" in outputs(model.calls[1][1])["call_1"]


async def test_box_answer_reaches_model(
    board: str, run_id: str, api: ApiClient, item_id: str
) -> None:
    say(board, run_id, "change the body")
    model = FakeChatModel(
        [call("confirm_part", {"item_id": item_id, "part": "body", "why": "Right?"}), reply("ok")]
    )
    await loop.run_turn(board, run_id, model, api)
    box = [0.1, 0.2, 0.3, 0.4]
    say(board, run_id, "here", {"answer": {"call_id": "call_1", "box": box}})
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    assert outputs(model.calls[1][1])["call_1"] == {"box": box}


async def test_hidden_tool_refused(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "finish up")
    model = FakeChatModel(
        [calls(("finish", {}, "c1"), ("no_such_tool", {}, "c2")), reply("I cannot finish.")]
    )
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    got = outputs(model.calls[1][1])
    assert got["c1"]["error"] == "NOT_AVAILABLE" and got["c2"]["error"] == "NOT_AVAILABLE"
    assert steps(run_id) == []


async def test_bad_arguments_refused(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "go")
    model = FakeChatModel(
        [
            calls(("read_board", {"_bad_arguments": True}, "c1"), ("ask_user", {}, "c2")),
            reply("Sorry."),
        ]
    )
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    got = outputs(model.calls[1][1])
    assert got["c1"]["error"] == "BAD_ARGUMENTS" and got["c2"]["error"] == "BAD_ARGUMENTS"
    assert steps(run_id) == []


async def test_look_at_sends_images(board: str, run_id: str, api: ApiClient, item_id: str) -> None:
    say(board, run_id, "what do you see?")
    model = FakeChatModel(
        [call("look_at", {"item_ids": [item_id, "itm_missing"]}), reply("A picture.")]
    )
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    second = model.calls[1][1]
    assert outputs(second)["call_1"] == {"ok": True, "missing": ["itm_missing"]}
    images = second[-1]
    assert images["role"] == "user" and "muse_person" not in images
    assert images["content"][0]["type"] == "input_text"
    assert images["content"][1]["type"] == "input_image"
    assert images["content"][1]["image_url"].startswith("data:image/")


async def test_selection_in_person_message(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "make this warmer", {"selection": ["itm_a", "itm_b"]})
    model = FakeChatModel([reply("ok")])
    await loop.run_turn(board, run_id, model, api)
    assert "Selected on the board: itm_a, itm_b" in input_text(model.calls[0][1])


async def test_stop_flag_halts_before_next_call(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "read it twice")
    model = FakeChatModel([calls(("read_board", {}, "c1"), ("read_board", {}, "c2"))])
    checks = iter([False, False])  # before the model call, before the first tool call
    status = await loop.run_turn(board, run_id, model, api, should_stop=lambda: next(checks, True))
    assert status == "waiting" and len(model.calls) == 1
    assert len(steps(run_id)) == 1
    _, history = run_row(run_id)
    assert outputs(history)["c2"]["error"] == "STOPPED"


async def test_stop_before_first_model_call(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "hi")
    model = FakeChatModel([])
    status = await loop.run_turn(board, run_id, model, api, should_stop=lambda: True)
    assert status == "waiting" and model.calls == []
    assert run_row(run_id)[1][0]["muse_person"] is True  # the message is kept in the history


async def test_step_cap_message(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "keep reading")
    model = FakeChatModel([call("read_board", {}, f"c{i}") for i in range(loop.MAX_STEPS)])
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    assert len(model.calls) == 40 == loop.MAX_STEPS
    assert thread(run_id)[-1]["text"] == "I stopped after 40 steps. Tell me how to continue."
    assert len(steps(run_id)) == 40


class FailingModel:
    def respond(self, *_args: Any) -> ModelTurn:
        raise ModelError("MODEL_TIMEOUT", message="took too long")


async def test_model_error_posts_message_and_waits(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "hello")
    assert await loop.run_turn(board, run_id, FailingModel(), api) == "waiting"
    last = thread(run_id)[-1]
    assert last["role"] == "agent"
    assert last["text"] == "Muse Spark failed (MODEL_TIMEOUT). Send a message to try again."
    assert run_row(run_id)[0] == "waiting"


async def test_message_during_turn_is_picked_up(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "read the board")
    model = FakeChatModel([call("read_board", {}), reply("ok, blue it is")])
    queued: list[dict[str, Any]] = []

    def next_message() -> dict[str, Any] | None:
        if queued:  # one message arrives, once
            return None
        queued.append(say(board, run_id, "and make it blue"))
        return queued[0]

    assert await loop.run_turn(board, run_id, model, api, next_message=next_message) == "waiting"
    second = model.calls[1][1]
    assert "and make it blue" in input_text(second)
    assert "[Board" not in input_text(second[-1:])  # only the first turn names the board
    with deps.new_session() as s:
        assert agent_repo.unconsumed_messages(s, run_id) == []


async def test_ended_run_is_left_alone(board: str, run_id: str, api: ApiClient) -> None:
    say(board, run_id, "hello")
    await run_state.update(run_id, status="done")
    model = FakeChatModel([])
    assert await loop.run_turn(board, run_id, model, api) == "done"
    assert model.calls == []


async def test_look_at_fetch_error_is_a_tool_failure(
    board: str, run_id: str, api: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(_path: str) -> bytes | None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(api, "get_bytes", broken)
    say(board, run_id, "look")
    model = FakeChatModel([call("look_at", {"item_ids": ["itm_x"]}), reply("I could not see it.")])
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    result = outputs(model.calls[1][1])["call_1"]
    assert result["error"] == "TOOL_FAILED" and "connection refused" in result["message"]
    assert thread(run_id)[-1]["text"] == "I could not see it."


async def test_unexpected_error_posts_message_and_waits(
    board: str, run_id: str, api: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_args: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(loop._Turn, "run_calls", broken)  # fails outside any tool guard
    say(board, run_id, "read")
    model = FakeChatModel([calls(("read_board", {}, "c1"), ("read_board", {}, "c2"))])
    assert await loop.run_turn(board, run_id, model, api) == "waiting"
    last = thread(run_id)[-1]
    assert last["role"] == "agent"
    assert last["text"] == "Something went wrong (RuntimeError). Send a message to try again."
    status, history = run_row(run_id)
    assert status == "waiting" and history[0]["muse_person"] is True
    got = outputs(history)
    assert got["c1"]["error"] == "TOOL_FAILED" and got["c2"]["error"] == "TOOL_FAILED"
