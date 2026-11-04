from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.chat.model import (
    FakeChatModel,
    ModelTurn,
    MuseSparkChat,
    ToolCall,
    get_chat_model,
)
from app.config import Settings


class _Item:
    def __init__(self, data: dict[str, Any]) -> None:
        self._d = data

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        return dict(self._d)


class _Usage:
    def model_dump(self) -> dict[str, Any]:
        return {"input_tokens": 3, "output_tokens": 4}


class _Client:
    def __init__(self, output: list[_Item]) -> None:
        self.kwargs: dict[str, Any] = {}
        self.responses = SimpleNamespace(create=self._create)
        self._output = output

    def _create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        text = "".join(
            p["text"] for o in self._output if o._d["type"] == "message" for p in o._d["content"]
        )
        return SimpleNamespace(output=self._output, output_text=text, usage=_Usage())


def _output(arguments: str) -> list[_Item]:
    return [
        _Item({"type": "reasoning", "encrypted_content": "abc"}),
        _Item({"type": "message", "content": [{"type": "output_text", "text": "hello"}]}),
        _Item({"type": "function_call", "name": "look", "arguments": arguments, "call_id": "c1"}),
    ]


TOOLS = [{"name": "look", "description": "d", "parameters": {"type": "object"}}]


def _chat(client: _Client) -> MuseSparkChat:
    return MuseSparkChat(client, "muse-spark", max_retries=0, timeout=5)  # type: ignore[arg-type]


def test_get_chat_model_none_for_mock() -> None:
    assert get_chat_model(Settings(REASONING_PROVIDER="mock", MODEL_API_KEY="k")) is None


def test_get_chat_model_none_without_key() -> None:
    assert get_chat_model(Settings(REASONING_PROVIDER="muse-spark", MODEL_API_KEY="")) is None


def test_muse_spark_chat_parses_calls() -> None:
    client = _Client(_output('{"a": 1}'))
    turn = _chat(client).respond("sys", [{"role": "user", "content": "hi"}], TOOLS)
    assert turn.text == "hello"
    assert turn.calls == [ToolCall("look", {"a": 1}, "c1")]
    assert [o["type"] for o in turn.output] == ["reasoning", "message", "function_call"]
    assert turn.usage == {"input_tokens": 3, "output_tokens": 4}
    assert turn.latency_s >= 0
    assert client.kwargs["tools"] == [{"type": "function", **TOOLS[0]}]
    assert client.kwargs["store"] is False
    assert client.kwargs["reasoning"] == {"effort": "medium"}
    assert client.kwargs["instructions"] == "sys"


def test_bad_arguments_flagged() -> None:
    turn = _chat(_Client(_output("{nope"))).respond("s", [], TOOLS)
    assert turn.calls[0].arguments == {"_bad_arguments": True}


def test_fake_chat_model_records_and_runs_out() -> None:
    fake = FakeChatModel([ModelTurn([], "x", [], {}, 0.0)])
    assert fake.respond("i", [], []).text == "x"
    assert fake.calls == [("i", [], [])]
    with pytest.raises(AssertionError, match="script"):
        fake.respond("i", [], [])


def test_fake_chat_model_records_a_copy_of_each_input() -> None:
    fake = FakeChatModel([ModelTurn([], "x", [], {}, 0.0)] * 2)
    history: list[dict[str, Any]] = [{"role": "user", "content": "a"}]
    fake.respond("i", history, [])
    history.append({"role": "user", "content": "b"})
    fake.respond("i", history, [])
    assert [len(c[1]) for c in fake.calls] == [1, 2]
