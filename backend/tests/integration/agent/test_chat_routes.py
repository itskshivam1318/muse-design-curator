"""The board chat routes and runner: a scripted model behind the HTTP API."""

import asyncio
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import events, jobs
from app.agent import run_state
from app.agent.chat import runner
from app.agent.chat.model import FakeChatModel, ModelTurn
from app.api import deps
from app.board import profile_hook
from app.db.repos import agent as agent_repo
from tests.integration.agent.test_chat_loop import call, calls, input_text, outputs, reply
from tests.integration.api.test_demo import PASSCODE, SECRET


@pytest.fixture(autouse=True)
def env(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)
    monkeypatch.setattr(jobs, "enqueue", lambda _name, **_kw: None)
    runner._boards.clear()
    runner._stopped.clear()
    yield
    runner._boards.clear()
    runner._stopped.clear()


def use(monkeypatch: pytest.MonkeyPatch, model: Any) -> Any:
    monkeypatch.setattr(runner, "get_chat_model", lambda _settings: model)
    return model


def script(monkeypatch: pytest.MonkeyPatch, *turns: ModelTurn) -> FakeChatModel:
    return use(monkeypatch, FakeChatModel(list(turns)))  # type: ignore[no-any-return]


def send(client: TestClient, board: str, text: str, **body: Any) -> Any:
    return client.post(f"/api/boards/{board}/agent/messages", json={"text": text, **body})


def thread(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    r = client.get(f"/api/agent-runs/{run_id}/messages")
    assert r.status_code == 200
    return r.json()["messages"]  # type: ignore[no-any-return]


def run_row(run_id: str) -> Any:
    with deps.new_session() as s:
        run = agent_repo.get_run(s, run_id)
        assert run is not None
        return agent_repo.run_to_dict(run)


def add_person(board: str, run_id: str, text: str) -> None:
    with deps.new_session() as s:
        agent_repo.add_message(s, run_id, board, "person", text)
        s.commit()


def unconsumed(run_id: str) -> list[str]:
    with deps.new_session() as s:
        return [m.text for m in agent_repo.unconsumed_messages(s, run_id)]


class Gated:
    """A scripted model whose first reply waits for `release`; it counts overlapping calls."""

    def __init__(self, *turns: ModelTurn) -> None:
        self.fake = FakeChatModel(list(turns))
        self.entered, self.release = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.now = self.most = 0

    @property
    def calls(self) -> list[Any]:
        return self.fake.calls

    def respond(self, instructions: str, input: Any, tools: Any) -> ModelTurn:
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
        try:
            if len(self.fake.calls) == 0:
                self.entered.set()
                assert self.release.wait(5)
            return self.fake.respond(instructions, input, tools)
        finally:
            with self.lock:
                self.now -= 1


async def until(flag: threading.Event) -> None:
    for _ in range(500):
        if flag.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


# --- sending ---------------------------------------------------------------------------------


def test_first_message_opens_muse_run(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = script(monkeypatch, reply("Hello."))
    r = send(client, board, "Make it warmer", selection=["itm_a"])
    assert r.status_code == 202
    run, message = r.json()["run"], r.json()["message"]
    assert run["source"] == "muse" and run["goal"] == "Make it warmer"
    assert run["status"] == "waiting"  # JOBS_SYNC: the turn ran inline
    assert message["role"] == "person" and message["data"] == {"selection": ["itm_a"]}
    assert [(m["role"], m["text"]) for m in thread(client, run["id"])] == [
        ("person", "Make it warmer"),
        ("agent", "Hello."),
    ]
    assert len(model.calls) == 1 and "Make it warmer" in input_text(model.calls[0][1])
    assert send(client, board, "").status_code in (400, 422)
    assert send(client, board, "x" * 2001).status_code in (400, 422)
    assert send(client, "board_nope", "hi").status_code == 404


def test_second_message_joins_run(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = script(monkeypatch, reply("One."), reply("Two."))
    first = send(client, board, "first").json()["run"]
    second = send(client, board, "second").json()["run"]
    assert second["id"] == first["id"] and second["goal"] == "first"
    text = input_text(model.calls[1][1])
    assert text.count("first") == 1 and text.count("second") == 1
    assert unconsumed(first["id"]) == []


async def test_second_message_does_not_start_second_loop(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A message sent during a turn is handed to that turn (once), not to a second loop."""
    model = use(monkeypatch, Gated(call("look_at", {}), reply("Both seen.")))
    run, _ = await run_state.start(board, "muse", "first", [])
    add_person(board, run["id"], "first")
    runner.kick(board, run["id"])
    task = runner._boards[board].task
    assert task is not None
    await until(model.entered)
    add_person(board, run["id"], "second")
    runner.kick(board, run["id"])
    assert runner._boards[board].task is task
    model.release.set()
    await task
    assert model.most == 1 and len(model.calls) == 2
    text = input_text(model.calls[1][1])
    assert text.count("first") == 1 and text.count("second") == 1
    assert unconsumed(run["id"]) == []
    assert run_row(run["id"])["status"] == "waiting"
    assert not runner._boards[board].active


async def test_message_after_reply_gets_another_turn(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = use(monkeypatch, Gated(reply("One."), reply("Two.")))
    run, _ = await run_state.start(board, "muse", "first", [])
    add_person(board, run["id"], "first")
    runner.kick(board, run["id"])
    task = runner._boards[board].task
    assert task is not None
    await until(model.entered)
    add_person(board, run["id"], "second")
    runner.kick(board, run["id"])
    model.release.set()
    await task
    assert model.most == 1 and len(model.calls) == 2
    assert input_text(model.calls[1][1]).count("first") == 1
    assert unconsumed(run["id"]) == []


def test_turn_crash_leaves_run_waiting(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script(monkeypatch)

    async def boom(*_a: Any, **_kw: Any) -> str:
        await run_state.update(run_id, status="running")
        raise RuntimeError("load failed")

    monkeypatch.setattr(runner, "run_turn", boom)
    with deps.new_session() as s:
        run_id = agent_repo.create_run(s, board, "muse", "g", []).id
        s.commit()
    r = send(client, board, "hi")
    assert r.status_code == 202 and r.json()["run"]["status"] == "waiting"
    last = thread(client, run_id)[-1]
    assert (last["role"], last["text"]) == ("agent", runner.FAILED_TEXT)
    assert not runner._boards[board].active


# --- questions -------------------------------------------------------------------------------


def test_answer_resumes_question(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = script(
        monkeypatch, call("ask_user", {"question": "Which?"}, "call_q"), reply("Red it is.")
    )
    run = send(client, board, "pick one").json()["run"]
    assert run["status"] == "needs_input"
    r = send(client, board, "red", answer={"call_id": "call_q", "choice": "red"})
    assert r.status_code == 202 and r.json()["run"]["status"] == "waiting"
    assert outputs(model.calls[1][1])["call_q"] == {"choice": "red"}
    question = next(m for m in thread(client, run["id"]) if m["role"] == "question")
    assert question["answered"] is True


def test_answer_closes_question_at_once(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer marks the question answered (and says so) before any turn runs; a repeat
    answer to it is refused."""
    script(monkeypatch, call("ask_user", {"question": "Which?"}, "call_q"))
    run = send(client, board, "pick one").json()["run"]
    kicked: list[str] = []

    async def no_turn(_board_id: str, run_id: str) -> None:
        kicked.append(run_id)

    monkeypatch.setattr(runner, "kick_sync", no_turn)
    with events.subscribe(board) as sub:
        r = send(client, board, "red", answer={"call_id": "call_q", "choice": "red"})
        seen = []
        while (ev := sub.get(timeout=0.2)) is not None:
            seen.append(ev)
    assert r.status_code == 202 and kicked == [run["id"]]
    question = next(m for m in thread(client, run["id"]) if m["role"] == "question")
    assert question["answered"] is True  # no turn has run yet
    updates = [e["data"] for e in seen if e["type"] == "agent.question"]
    assert updates == [question]
    again = send(client, board, "blue", answer={"call_id": "call_q", "choice": "blue"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "NO_OPEN_QUESTION"
    box = send(client, board, "here", answer={"call_id": "call_q", "box": [0, 0, 1, 1]})
    assert box.status_code == 409
    assert [m["text"] for m in thread(client, run["id"]) if m["role"] == "person"] == [
        "pick one", "red",
    ]  # fmt: skip


def test_stale_answer_rejected(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script(monkeypatch, call("ask_user", {"question": "Which?"}, "call_q"))
    nothing = send(client, board, "red", answer={"call_id": "call_q", "text": "red"})
    assert nothing.status_code == 409 and nothing.json()["error"]["code"] == "NO_OPEN_QUESTION"
    assert client.get(f"/api/boards/{board}/agent-runs").json()["runs"] == []  # none opened
    run = send(client, board, "pick one").json()["run"]
    before = thread(client, run["id"])
    stale = send(client, board, "red", answer={"call_id": "call_old", "text": "red"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "NO_OPEN_QUESTION"
    assert thread(client, run["id"]) == before


def test_text_while_question_open_is_answer(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = script(monkeypatch, call("ask_user", {"question": "Which?"}, "call_q"), reply("Ok."))
    send(client, board, "pick one")
    r = send(client, board, "blue")
    assert r.status_code == 202
    assert r.json()["message"]["data"] == {"answer": {"call_id": "call_q", "text": "blue"}}
    assert outputs(model.calls[1][1])["call_q"] == {"answer": "blue"}
    assert input_text(model.calls[1][1]).count("blue") == 0  # an output, not a new person turn


# --- stop and new chat -----------------------------------------------------------------------


async def test_stop_sets_waiting(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    two = calls(("look_at", {}, "call_1"), ("look_at", {}, "call_2"))
    model = use(monkeypatch, Gated(two))
    run, _ = await run_state.start(board, "muse", "go", [])
    add_person(board, run["id"], "go")
    runner.kick(board, run["id"])
    task = runner._boards[board].task
    assert task is not None
    await until(model.entered)
    r = client.patch(f"/api/agent-runs/{run['id']}", json={"status": "paused"})
    assert r.status_code == 200 and r.json()["status"] == "waiting"
    model.release.set()
    await task
    assert len(model.calls) == 1  # no model call after the stop
    with deps.new_session() as s:
        row = agent_repo.get_run(s, run["id"])
        assert row is not None
        assert row.status == "waiting"
        assert {o["error"] for o in outputs(row.history_json or []).values()} == {"STOPPED"}


def test_new_chat_done_then_new_run(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script(monkeypatch, reply("One."), reply("Two."))
    first = send(client, board, "first chat").json()["run"]
    r = client.post(f"/api/agent-runs/{first['id']}/new-chat")
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert first["id"] in runner._stopped  # a turn in flight would stop calling tools
    second = send(client, board, "second chat").json()["run"]
    assert second["id"] != first["id"] and second["goal"] == "second chat"
    assert run_row(first["id"])["status"] == "done"
    assert [m["text"] for m in thread(client, second["id"])] == ["second chat", "Two."]
    assert client.post("/api/agent-runs/agent_run_nope/new-chat").status_code == 404


# --- refusals --------------------------------------------------------------------------------


def test_refused_in_demo_mode(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script(monkeypatch, reply("never"))
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", PASSCODE)
    monkeypatch.setenv("DEMO_SECRET", SECRET)
    assert client.post("/api/demo/unlock", json={"passcode": PASSCODE}).status_code == 200
    r = send(client, board, "hi")
    assert r.status_code == 409 and r.json()["error"] == {
        **r.json()["error"], "code": "CHAT_UNAVAILABLE", "message": "Chat is off in the demo.",
    }  # fmt: skip
    assert client.get("/api/agent/chat-status").json() == {
        "available": False, "reason": "Chat is off in the demo.",
    }  # fmt: skip


def test_refused_without_chat_model(client: TestClient, board: str) -> None:
    reason = "Chat needs Muse Spark (REASONING_PROVIDER=muse-spark)."
    r = send(client, board, "hi")  # the tests' REASONING_PROVIDER is mock
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHAT_UNAVAILABLE"
    assert r.json()["error"]["message"] == reason
    assert client.get("/api/agent/chat-status").json() == {"available": False, "reason": reason}
    assert client.get(f"/api/boards/{board}/agent-runs").json()["runs"] == []


def test_chat_status_available(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch)
    assert client.get("/api/agent/chat-status").json() == {"available": True, "reason": None}


async def test_refused_while_mcp_run_open(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script(monkeypatch)
    await run_state.start(board, "mcp", "g", ["board"])
    r = send(client, board, "hi")
    assert r.status_code == 409 and r.json()["error"]["code"] == "MCP_RUN_OPEN"


# --- reading ---------------------------------------------------------------------------------


def test_trace_route(client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch) -> None:
    script(monkeypatch, reply("Hello."))
    run = send(client, board, "hi").json()["run"]
    r = client.get(f"/api/agent-runs/{run['id']}/trace")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    records = [json.loads(line) for line in r.text.splitlines()]
    assert records and all("t" in rec for rec in records)
    monkeypatch.setenv("AGENT_TRACES", "0")
    off = client.get(f"/api/agent-runs/{run['id']}/trace")
    assert off.status_code == 404 and off.json()["error"]["code"] == "TRACE_NOT_FOUND"
    monkeypatch.setenv("AGENT_TRACES", "1")
    with deps.new_session() as s:
        quiet = agent_repo.create_run(s, board, "mcp", "g", []).id
        s.commit()
    assert client.get(f"/api/agent-runs/{quiet}/trace").status_code == 404
    assert client.get("/api/agent-runs/agent_run_nope/trace").status_code == 404


def test_messages_route_order(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script(monkeypatch, reply("A1"), reply("A2"))
    run = send(client, board, "P1").json()["run"]
    send(client, board, "P2")
    assert [(m["role"], m["text"]) for m in thread(client, run["id"])] == [
        ("person", "P1"), ("agent", "A1"), ("person", "P2"), ("agent", "A2"),
    ]  # fmt: skip
    missing = client.get("/api/agent-runs/agent_run_nope/messages")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_startup_resets_running_chat_runs(client: TestClient, board: str) -> None:
    from app.main import app

    other = client.post("/api/boards", json={"title": "Other"}).json()["id"]
    with deps.new_session() as s:
        chat = agent_repo.create_run(s, board, "muse", "g", [])
        chat.status = "running"
        mcp = agent_repo.create_run(s, other, "mcp", "g", [])
        mcp.status = "running"
        s.commit()
        chat_id, mcp_id = chat.id, mcp.id
    with TestClient(app):  # the lifespan runs the reset
        pass
    assert run_row(chat_id)["status"] == "waiting"
    assert run_row(mcp_id)["status"] == "running"
    with deps.new_session() as s:
        again = agent_repo.get_run(s, chat_id)
        assert again is not None
        again.status = "running"
        s.commit()
    assert runner.reset_running_on_startup() == 1
    assert runner.reset_running_on_startup() == 0
