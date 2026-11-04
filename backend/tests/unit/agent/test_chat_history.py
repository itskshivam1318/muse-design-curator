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
    assert last["type"] == "function_call_output" and len(last["output"]) <= 6000
    got = json.loads(last["output"])  # cut inside the JSON, never mid-text
    assert got["v"].startswith("xxx") and got["truncated"]


def board_output(n: int) -> str:
    items = [{"id": f"itm_{i:03}", "origin": "upload", "title": "t" * 120} for i in range(n)]
    return json.dumps(
        {
            "board": {"id": "brd_1"},
            "items": items,
            "profile": {"summary": "warm"},
            "context": "cars",
        }
    )


def test_big_json_output_stays_valid_json() -> None:
    h = [
        person("one"),
        {"type": "function_call", "name": "get_items", "arguments": "{}", "call_id": "a"},
        {"type": "function_call_output", "call_id": "a", "output": board_output(200)},
    ]
    [_, _, kept] = compact(h)
    assert len(kept["output"]) <= 6000
    got = json.loads(kept["output"])
    assert got["truncated"] and 0 < len(got["items"]) < 200
    assert got["items"][0]["id"] == "itm_000"  # lists keep their head
    assert got["profile"] == {"summary": "warm"} and got["context"] == "cars"  # the tail survives


def test_text_output_falls_back_to_valid_json() -> None:
    h = [
        person("one"),
        {"type": "function_call", "name": "t", "arguments": "{}", "call_id": "a"},
        {"type": "function_call_output", "call_id": "a", "output": 'say "hi" ' * 2000},
    ]
    kept = compact(h)[-1]
    assert len(kept["output"]) <= 6000
    assert json.loads(kept["output"])["summary"].startswith('say "hi"')


def test_read_board_whole_in_the_current_turn() -> None:
    def read(cid: str) -> list[dict[str, Any]]:
        return [
            {"type": "function_call", "name": "read_board", "arguments": "{}", "call_id": cid},
            {"type": "function_call_output", "call_id": cid, "output": board_output(60)},
        ]

    out = compact([person("one"), *read("a"), person("two"), *read("b")])
    earlier, now = out[2], out[-1]
    assert now["output"] == board_output(60)  # this turn's board read is whole
    assert len(earlier["output"]) <= 6000 and json.loads(earlier["output"])["truncated"]


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
