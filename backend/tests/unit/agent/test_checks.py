from typing import Any

import pytest

from app.agent import checks
from app.providers.reliability import ModelError


def _explore(answer: str, drifted: list[str] | None = None) -> dict[str, Any]:
    return {
        "target": {"answer": answer},
        "kept": 3,
        "of": 3,
        "drifted": drifted or [],
        "unknown": 0,
    }


def test_check_passed_explore() -> None:
    assert checks.check_passed(_explore("yes")) is True
    assert checks.check_passed(_explore("no")) is False
    assert checks.check_passed(_explore("unclear")) is False
    assert checks.check_passed(_explore("yes", ["roofline"])) is False


def test_check_passed_note() -> None:
    assert checks.check_passed({"target_ok": True, "answer": "yes"}) is True
    assert checks.check_passed({"target_ok": False, "answer": "no"}) is False
    assert checks.check_passed({"target_ok": None, "answer": "unclear"}) is False


def test_check_passed_error_and_unchecked() -> None:
    assert checks.check_passed({"error": "MODEL_TIMEOUT"}) is False
    assert checks.check_passed(None) is None
    assert checks.check_passed({}) is None


def _run(deliverables: list[str], sections: list[dict[str, Any]] | None) -> dict[str, Any]:
    output = None if sections is None else {"title": "T", "sections": sections, "note_ids": []}
    return {"goal": "g", "deliverables": deliverables, "output": output}


def _section(deliverable: str, *item_ids: str) -> dict[str, Any]:
    return {"deliverable": deliverable, "items": [{"item_id": i, "why": "w"} for i in item_ids]}


def test_deliverable_problems_none_when_delivered() -> None:
    run = _run(["front", "side"], [_section("front", "itm_a"), _section("side", "itm_b")])
    items = {"itm_a": {"check": _explore("yes")}, "itm_b": {"check": None}}
    assert checks.deliverable_problems(run, items) == []


def test_deliverable_problems_missing() -> None:
    assert checks.deliverable_problems(_run(["front"], None), {}) == ["'front' has no item"]
    run = _run(["front", "exterior side"], [_section("front", "itm_a"), _section("exterior side")])
    assert checks.deliverable_problems(run, {"itm_a": {"check": None}}) == [
        "'exterior side' has no item"
    ]


def test_deliverable_problems_removed() -> None:
    run = _run(["front"], [_section("front", "itm_a", "itm_gone")])
    problems = checks.deliverable_problems(run, {"itm_a": {"check": None}})
    assert problems == ["itm_gone was removed from the board"]


def test_deliverable_problems_failed_check() -> None:
    run = _run(["front"], [_section("front", "itm_a", "itm_b", "itm_c")])
    items = {
        "itm_a": {"check": _explore("yes", ["roofline"])},
        "itm_b": {"check": {"target_ok": False, "answer": "no"}},
        "itm_c": {"check": {"error": "MODEL_TIMEOUT"}},
    }
    assert checks.deliverable_problems(run, items) == [
        "itm_a failed its result check (drifted: roofline)",
        "itm_b failed its result check (answer: no)",
        "itm_c failed its result check (error: MODEL_TIMEOUT)",
    ]


class _Reasoning:
    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[int, dict[str, Any], str]] = []

    def structured(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> Any:
        self.calls.append((len(images), schema, prompt))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _provide(monkeypatch: pytest.MonkeyPatch, fake: _Reasoning) -> None:
    monkeypatch.setattr(checks, "get_reasoning", lambda settings: fake)


def test_consistency_problems_names_outliers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Reasoning({"one_design": False, "outliers": [1], "reason": "a different roof"})
    _provide(monkeypatch, fake)
    problems = checks.consistency_problems(
        [b"a", b"b", b"c"], "a cabin", ["itm_a", "itm_b", "itm_c"]
    )
    assert problems == ["itm_b does not show the same design as the rest: a different roof"]
    count, schema, prompt = fake.calls[0]
    assert count == 3 and schema == checks.CONSISTENCY_SCHEMA and "a cabin" in prompt


def test_consistency_problems_one_design(monkeypatch: pytest.MonkeyPatch) -> None:
    _provide(monkeypatch, _Reasoning({"one_design": True, "outliers": [], "reason": ""}))
    assert checks.consistency_problems([b"a", b"b"], "g", ["itm_a", "itm_b"]) == []


def test_consistency_problems_caps_images(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Reasoning({"one_design": True, "outliers": [], "reason": ""})
    _provide(monkeypatch, fake)
    checks.consistency_problems([b"x"] * 20, "g", [f"itm_{i}" for i in range(20)])
    assert fake.calls[0][0] == 12


def test_consistency_problems_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _provide(monkeypatch, _Reasoning(ModelError("MODEL_TIMEOUT")))
    assert checks.consistency_problems([b"a", b"b"], "g", ["itm_a", "itm_b"]) == [
        "consistency check unavailable: MODEL_TIMEOUT"
    ]


def test_consistency_problems_without_valid_outliers(monkeypatch: pytest.MonkeyPatch) -> None:
    _provide(monkeypatch, _Reasoning({"one_design": False, "outliers": [7], "reason": "mixed"}))
    assert checks.consistency_problems([b"a", b"b"], "g", ["itm_a", "itm_b"]) == [
        "the output does not show one design: mixed"
    ]
