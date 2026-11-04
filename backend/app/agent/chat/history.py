"""Chat history compaction: old turns shrink, recent turns stay whole."""

from __future__ import annotations

import json
from typing import Any

__all__ = ["compact"]

_SUMMARY_CHARS = 200
_KEPT_OUTPUT_CHARS = 6000
_MARKER = "muse_person"


def _is_person(item: dict[str, Any]) -> bool:
    return item.get("role") == "user" and bool(item.get(_MARKER))


def _clean(item: dict[str, Any]) -> dict[str, Any]:
    """A shallow copy without our own marker, which the API may reject."""
    return {k: v for k, v in item.items() if k != _MARKER}


def _squash_old(item: dict[str, Any]) -> dict[str, Any]:
    out = _clean(item)
    if out.get("type") == "function_call_output":
        out["output"] = json.dumps({"summary": str(out.get("output", ""))[:_SUMMARY_CHARS]})
    elif isinstance(out.get("content"), list):
        out["content"] = [
            p
            for p in out["content"]
            if not (isinstance(p, dict) and p.get("type") == "input_image")
        ]
    return out


def _cap_kept(item: dict[str, Any]) -> dict[str, Any]:
    out = _clean(item)
    if out.get("type") == "function_call_output":
        out["output"] = str(out.get("output", ""))[:_KEPT_OUTPUT_CHARS]
    return out


def compact(items: list[dict[str, Any]], keep_turns: int = 2) -> list[dict[str, Any]]:
    """Return a compacted copy of the history; the stored list is never mutated.

    A turn starts at each person message. Before the last ``keep_turns`` turns, tool
    outputs shrink to a summary and images and reasoning are dropped; inside them, tool
    outputs are capped. Calls and their outputs are kept in pairs.
    """
    starts = [i for i, it in enumerate(items) if _is_person(it)]
    cutoff = (
        starts[-keep_turns]
        if keep_turns > 0 and len(starts) >= keep_turns
        else (len(items) if keep_turns <= 0 else 0)
    )
    result: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if i < cutoff:
            if item.get("type") == "reasoning":
                continue
            result.append(_squash_old(item))
        else:
            result.append(_cap_kept(item))
    return result
