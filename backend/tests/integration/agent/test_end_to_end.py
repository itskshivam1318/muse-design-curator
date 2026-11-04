"""One MCP session takes a goal to a finished run, as Claude Code would over /mcp."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import events
from app.api.deps import new_session
from app.db.models import AgentRun
from app.db.repos import agent as agent_repo
from app.providers.reasoning import MockReasoningProvider
from tests.integration.agent.test_mcp import McpSession

DELIVERABLES = ["front view", "colour option"]


def _drain(sub: Any) -> list[dict[str, Any]]:
    seen = []
    while (ev := sub.get(timeout=0.2)) is not None:
        seen.append(ev)
    return seen


def _yes(self: MockReasoningProvider, images: list[bytes], prompt: str) -> dict[str, Any]:
    return {"answer": "yes", "confidence": 0.9, "box": None, "note": ""}


def test_goal_to_done_over_mcp(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "1")
    # The mock's answer hangs on a hash of the prompt; every render here matches its note.
    monkeypatch.setattr(MockReasoningProvider, "check_target", _yes)
    session = McpSession(client)
    calls: list[str] = []

    def tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(name)
        result = session.tool(name, {**args, "say": f"Calling {name}."})
        assert "error" not in result, (name, result)
        return result

    board_id = tool("create_board", {"title": "End to end"})["board_id"]
    with events.subscribe(board_id) as sub:
        run_id = tool("set_goal", {"goal": "A test chair", "deliverables": DELIVERABLES})[
            "run_id"
        ]
        notes = [
            tool("add_note", {"text": "a low oak chair, front view", "x": 0, "y": 0}),
            tool("add_note", {"text": "the same chair in deep green", "x": 600, "y": 0}),
        ]
        made: list[str] = []
        for note in notes:
            tool("visualize_note", {"note_id": note["item_id"]})
        for note in notes:
            waited = tool("wait", {"kind": "note", "id": note["item_id"], "timeout_s": 30})
            assert waited["timed_out"] is False, waited
            assert waited["result"]["item_id"], waited
            made.append(waited["result"]["item_id"])
        sections = [
            {"deliverable": d, "items": [{"item_id": i, "why": f"shows the {d}"}]}
            for d, i in zip(DELIVERABLES, made, strict=True)
        ]
        tool("compose_output", {"title": "A test chair", "sections": sections})
        assert tool("finish", {"summary": "A front view and a colour option."}) == {
            "status": "done"
        }
        seen = {e["type"] for e in _drain(sub)}

    with new_session() as s:
        run = s.get(AgentRun, run_id)
        assert run is not None and run.status == "done"
        steps = agent_repo.steps(s, run_id)
        logged = [(st.tool, st.say) for st in steps]
    # create_board runs before the goal opens the run; every call from set_goal on is a step.
    assert logged == [(name, f"Calling {name}.") for name in calls[1:]]
    assert {"agent.run", "agent.step", "item.added"} <= seen
