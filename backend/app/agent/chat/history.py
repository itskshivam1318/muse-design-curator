"""Chat history compaction: old turns shrink, recent turns stay whole."""

from __future__ import annotations

import json
from typing import Any

__all__ = ["compact"]

_SUMMARY_CHARS = 200
_KEPT_OUTPUT_CHARS = 6000
_MIN_TEXT_CHARS = 80  # a long string is cut no shorter than this
_MARKER = "muse_person"
# tools whose output is bounded by the tool itself: whole in the turn that called them
_WHOLE_NOW = {"read_board"}
_CUT_NOTE = "shortened to fit: long lists keep their first entries, long text its start"


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


def _dump(value: Any) -> str:
    return json.dumps(value, default=str)


def _cuttable(child: Any, kind: type) -> bool:
    if kind is list:
        return isinstance(child, list) and len(child) > 1
    return isinstance(child, str) and len(child) > _MIN_TEXT_CHARS


def _largest(value: Any, kind: type) -> tuple[int, Any, Any] | None:
    """The largest list (len > 1) or string (longer than _MIN_TEXT_CHARS) inside `value`, as
    (its JSON size, its container, its key in the container)."""
    best: tuple[int, Any, Any] | None = None
    pairs: Any = value.items() if isinstance(value, dict) else enumerate(value)
    for key, child in pairs:
        if _cuttable(child, kind):
            size = len(_dump(child))
            if best is None or size > best[0]:
                best = (size, value, key)
        if isinstance(child, (dict, list)):
            inner = _largest(child, kind)
            if inner is not None and (best is None or inner[0] > best[0]):
                best = inner
    return best


def _shrink(value: dict[str, Any] | list[Any], limit: int) -> str | None:
    """`value` cut down to at most `limit` characters of JSON: the largest list loses its tail,
    then the longest text; None when that is not enough."""
    out: dict[str, Any] = (
        {"truncated": _CUT_NOTE, **value} if isinstance(value, dict) else
        {"truncated": _CUT_NOTE, "items": value}
    )  # fmt: skip
    out = json.loads(_dump(out))  # a deep copy: the stored history is never mutated
    for _ in range(500):
        text = _dump(out)
        excess = len(text) - limit
        if excess <= 0:
            return text
        found = _largest(out, list)
        if found is not None:
            size, container, key = found
            items = container[key]
            keep = max(1, min(len(items) - 1, int(len(items) * (1 - excess / size))))
            container[key] = items[:keep]
            continue
        found = _largest(out, str)
        if found is None:
            return None
        _size, container, key = found
        text_value = container[key]
        container[key] = text_value[: max(_MIN_TEXT_CHARS, len(text_value) - excess - 1)] + "…"
    return None


def _fit(text: str, limit: int) -> str:
    """A tool output of at most `limit` characters that is still valid JSON."""
    if len(text) <= limit:
        return text
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, (dict, list)):
        shrunk = _shrink(value, limit)
        if shrunk is not None:
            return shrunk
    cut = limit
    while True:
        out = _dump({"truncated": _CUT_NOTE, "summary": text[:cut]})
        if len(out) <= limit:
            return out
        cut = max(0, cut - (len(out) - limit))


def _cap_kept(item: dict[str, Any], whole: bool = False) -> dict[str, Any]:
    out = _clean(item)
    if out.get("type") == "function_call_output" and not whole:
        out["output"] = _fit(str(out.get("output", "")), _KEPT_OUTPUT_CHARS)
    return out


def compact(items: list[dict[str, Any]], keep_turns: int = 2) -> list[dict[str, Any]]:
    """Return a compacted copy of the history; the stored list is never mutated.

    A turn starts at each person message. Before the last ``keep_turns`` turns, tool
    outputs shrink to a summary and images and reasoning are dropped; inside them, tool
    outputs are capped, cut inside their JSON so they stay valid (a `read_board` output in the
    current turn is kept whole: the tool bounds it). Calls and their outputs are kept in pairs.
    """
    starts = [i for i, it in enumerate(items) if _is_person(it)]
    cutoff = (
        starts[-keep_turns]
        if keep_turns > 0 and len(starts) >= keep_turns
        else (len(items) if keep_turns <= 0 else 0)
    )
    now = starts[-1] if starts else 0  # the current turn starts at the last person message
    names = {it.get("call_id"): it.get("name") for it in items if it.get("type") == "function_call"}
    result: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if i < cutoff:
            if item.get("type") == "reasoning":
                continue
            result.append(_squash_old(item))
        else:
            whole = i >= now and names.get(item.get("call_id")) in _WHOLE_NOW
            result.append(_cap_kept(item, whole))
    return result
