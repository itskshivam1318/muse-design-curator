from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.chat.model import ModelTurn, ToolCall
from app.agent.chat.trace import Trace


def _turn() -> ModelTurn:
    return ModelTurn(
        output=[{"type": "reasoning", "encrypted_content": "q" * 50}],
        text="hi",
        calls=[ToolCall("t", {"a": 1}, "c1")],
        usage={"input_tokens": 3},
        latency_s=0.5,
    )


def test_trace_scrubs_images_and_reasoning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TRACES", "true")
    t = Trace("run1", tmp_path)
    new = [
        {
            "role": "user",
            "content": [{"type": "input_image", "image_url": "data:image/png;base64,AAAA"}],
        }
    ]
    t.model_call(1, 0, 4, new, _turn())
    t.tool("t", {"a": 1}, {"ok": True}, 0.1)
    t.message("assistant", "hi")
    lines = (tmp_path / "agent_traces" / "run1.jsonl").read_text().splitlines()
    assert len(lines) == 3
    blob = "\n".join(lines)
    assert "AAAA" not in blob and "q" * 50 not in blob
    first = json.loads(lines[0])
    assert first["new_items"][0]["content"][0]["image_url"] == "<image 26 chars>"
    assert first["output"][0]["encrypted_content"] == "<encrypted 50 chars>"
    assert first["calls"][0]["call_id"] == "c1"


def test_trace_off_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TRACES", "false")
    t = Trace("run2", tmp_path)
    t.model_call(1, 0, 1, [], _turn())
    t.tool("t", {}, {}, 0.0)
    t.message("user", "x")
    assert not (tmp_path / "agent_traces").exists()
