"""JSONL traces of a chat run: what the model saw and did, scrubbed of bulk."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.agent.chat.model import ModelTurn
from app.config import data_dir, get_settings

__all__ = ["Trace", "trace_path"]


def trace_path(run_id: str) -> Path:
    return data_dir(get_settings()) / "agent_traces" / f"{run_id}.jsonl"


def _scrub(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, key) for v in value]
    if isinstance(value, str):
        if key == "encrypted_content":
            return f"<encrypted {len(value)} chars>"
        if value.startswith("data:"):
            return f"<image {len(value)} chars>"
    return value


class Trace:
    def __init__(self, run_id: str, data_dir: Path) -> None:
        self.path = Path(data_dir) / "agent_traces" / f"{run_id}.jsonl"
        self.enabled = get_settings().AGENT_TRACES

    def _write(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"t": time.time(), **_scrub(record)}, default=str)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def model_call(
        self,
        turn: int,
        step: int,
        request_items_count: int,
        new_items: list[dict[str, Any]],
        turn_result: ModelTurn,
    ) -> None:
        self._write(
            {
                "kind": "model_call",
                "turn": turn,
                "step": step,
                "request_items_count": request_items_count,
                "new_items": new_items,
                "output": turn_result.output,
                "text": turn_result.text,
                "calls": [
                    {"name": c.name, "arguments": c.arguments, "call_id": c.call_id}
                    for c in turn_result.calls
                ],
                "usage": turn_result.usage,
                "latency_s": turn_result.latency_s,
            }
        )

    def tool(self, name: str, args: dict[str, Any], result: Any, latency_s: float) -> None:
        self._write(
            {"kind": "tool", "name": name, "args": args, "result": result, "latency_s": latency_s}
        )

    def message(self, role: str, text: str) -> None:
        self._write({"kind": "message", "role": role, "text": text})
