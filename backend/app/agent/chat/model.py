"""The chat agent's model client: one Responses API turn with function tools."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

from app.config import Settings
from app.providers.meta_client import check_model_id, get_client
from app.providers.reliability import ModelError, call_model

__all__ = [
    "ChatModel",
    "FakeChatModel",
    "ModelError",
    "ModelTurn",
    "MuseSparkChat",
    "ToolCall",
    "get_chat_model",
]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str


@dataclass
class ModelTurn:
    output: list[dict[str, Any]]
    text: str
    calls: list[ToolCall]
    usage: dict[str, Any]
    latency_s: float


class ChatModel(Protocol):
    def respond(
        self, instructions: str, input: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelTurn: ...


def _parse_call(item: dict[str, Any]) -> ToolCall:
    try:
        args = json.loads(item.get("arguments") or "{}")
        if not isinstance(args, dict):
            raise TypeError("arguments is not an object")
    except (ValueError, TypeError):
        args = {"_bad_arguments": True}
    return ToolCall(item["name"], args, item["call_id"])


class MuseSparkChat:
    def __init__(
        self, client: openai.OpenAI, model: str, *, max_retries: int = 2, timeout: float = 60
    ) -> None:
        self.client = client
        self.model = check_model_id(model)
        self.max_retries = max_retries
        self.timeout = timeout

    def respond(
        self, instructions: str, input: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelTurn:
        started = time.monotonic()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input,
            "tools": [{"type": "function", **t} for t in tools],
            "reasoning": {"effort": "medium"},
            "store": False,
        }

        def go() -> Any:
            return self.client.responses.create(**kwargs)

        resp = call_model(go, timeout=self.timeout, max_retries=self.max_retries)
        latency = time.monotonic() - started
        output = [o.model_dump(exclude_none=True) for o in resp.output]
        calls = [_parse_call(o) for o in output if o.get("type") == "function_call"]
        usage = resp.usage.model_dump() if resp.usage is not None else {}
        return ModelTurn(output, resp.output_text or "", calls, usage, latency)


@dataclass
class FakeChatModel:
    script: list[ModelTurn]
    calls: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = field(
        default_factory=list
    )

    def respond(
        self, instructions: str, input: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelTurn:
        # copies: the caller keeps extending the same history list after each call
        self.calls.append((instructions, copy.deepcopy(input), copy.deepcopy(tools)))
        if len(self.calls) > len(self.script):
            raise AssertionError(
                f"FakeChatModel script exhausted: {len(self.script)} turn(s) scripted, "
                f"respond() called {len(self.calls)} times"
            )
        return self.script[len(self.calls) - 1]


def get_chat_model(settings: Settings) -> ChatModel | None:
    if settings.REASONING_PROVIDER != "muse-spark" or not settings.MODEL_API_KEY:
        return None
    return MuseSparkChat(
        get_client(settings),
        settings.MUSE_SPARK_MODEL,
        max_retries=settings.MODEL_MAX_RETRIES,
        timeout=settings.MODEL_TIMEOUT_S,
    )
