from __future__ import annotations

import copy
import json
from typing import Any

from app.agent.chat.history import compact

IMG = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}


def person(text: str) -> dict[str, Any]:
    return {
        "role": "user",
        "muse_person": True,
        "content": [{"type": "input_text", "text": text}, IMG],
    }


def call(cid: str) -> list[dict[str, Any]]:
    return [
        {"type": "reasoning", "encrypted_content": "zzz"},
        {"type": "function_call", "name": "t", "arguments": "{}", "call_id": cid},
        {"type": "function_call_output", "call_id": cid, "output": json.dumps({"v": "x" * 20000})},
    ]


def history() -> list[dict[str, Any]]:
    return [person("one"), *call("a"), person("two"), *call("b"), person("three"), *call("c")]


def test_old_tool_outputs_summarised() -> None:
    out = compact(history())
    first = next(i for i in out if i.get("call_id") == "a" and i["type"] == "function_call_output")
    s = json.loads(first["output"])["summary"]
    assert len(s) == 200


def test_old_images_dropped() -> None:
    out = compact(history())
    assert all(p["type"] != "input_image" for p in out[0]["content"])
    people = [i for i in out if "content" in i]
    assert any(p["type"] == "input_image" for p in people[1]["content"])


def test_old_reasoning_removed() -> None:
    out = compact(history())
    assert sum(1 for i in out if i.get("type") == "reasoning") == 2


def test_kept_turns_untouched() -> None:
    h = history()
    out = compact(h)
    kept = [i for i in out if "content" in i][1:]
    assert [i["content"] for i in kept] == [i["content"] for i in h if "content" in i][1:]
    assert out[-2] == h[-2]


def test_long_tool_output_capped() -> None:
    out = compact(history())
    last = out[-1]
    assert last["type"] == "function_call_output" and len(last["output"]) == 6000


def test_call_output_pairs_preserved() -> None:
    out = compact(history())
    calls = {i["call_id"] for i in out if i.get("type") == "function_call"}
    outs = {i["call_id"] for i in out if i.get("type") == "function_call_output"}
    assert calls == outs == {"a", "b", "c"}


def test_marker_stripped_from_output() -> None:
    h = history()
    before = copy.deepcopy(h)
    out = compact(h)
    assert all("muse_person" not in i for i in out)
    assert h == before


def test_few_turns_nothing_old() -> None:
    out = compact([person("only"), *call("a")])
    assert out[0]["content"][1] == IMG
    assert out[1]["type"] == "reasoning"
