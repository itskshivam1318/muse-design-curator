from typing import Any

from app.domain.attributes import AttributeRecord
from app.domain.kinds import EnumSpec, NumberSpec, OrdinalSpec
from app.explore.prompts import build_check_prompt, build_explore_prompt
from app.explore.schema import CHECK_SCHEMA, OPTIONS_SCHEMA
from app.providers.reasoning import MockReasoningProvider

SPEC = EnumSpec(key="markers", label="Markers", category="dial", vocabulary=["arabic", "roman"])
OPEN_SPEC = EnumSpec(key="markers", label="Markers", category="dial", open_vocabulary=True)


def rec(key: str, label: str, value: Any) -> AttributeRecord:
    return AttributeRecord(key=key, label=label, category="x", kind="enum", value=value,
                           confidence=0.9, status="extracted", source="model")  # fmt: skip


ATTRS = [rec("markers", "Markers", "arabic"), rec("strap_material", "Strap material", "leather")]


def prompt(**over: Any) -> str:
    kw: dict[str, Any] = {
        "spec": SPEC, "current": "arabic", "attributes": ATTRS, "board_title": "Field watches",
        "board_context": "military dials", "existing_names": [], "parent": None, "steer": None,
        "mode": "initial",
    }  # fmt: skip
    kw.update(over)
    return build_explore_prompt(**kw)


def test_prompt_names_attribute_current_and_board() -> None:
    p = prompt()
    assert "Markers" in p and "arabic" in p and "Field watches" in p and "military dials" in p
    assert "strap_material" in p and "leather" in p  # keys the model may put in keeps


def test_prompt_lists_existing_names_to_avoid() -> None:
    p = prompt(mode="more", existing_names=["Sector dial", "Only the 12"])
    assert "Sector dial" in p and "Only the 12" in p and "do not repeat" in p.lower()


def test_prompt_further_asks_bolder() -> None:
    assert "bolder" in prompt(mode="further").lower()


def test_prompt_branch_mentions_parent() -> None:
    p = prompt(parent={"name": "Devanagari numerals", "description": "Script swap",
                       "distance": "bold", "value": "devanagari"})  # fmt: skip
    assert "Devanagari numerals" in p and "Script swap" in p


def test_prompt_steer_is_included() -> None:
    assert "only non-Latin scripts" in prompt(steer="only non-Latin scripts")


def test_prompt_vocabulary_is_inspiration_not_limit() -> None:
    p = prompt()
    assert "roman" in p and "beyond" in p.lower()
    assert "not a list to repeat" in p.lower() or "do not just list" in p.lower()


def test_unknown_current_value_is_stated() -> None:
    p = prompt(current=None)
    assert "unknown" in p.lower() and "not read" in p.lower()


def test_prompt_per_kind_value_hints() -> None:
    num = NumberSpec(key="n", label="Count", category="c", unit="mm", min=0, max=10, tolerance=1)
    assert "0" in prompt(spec=num, current=3.0) and "10" in prompt(spec=num, current=3.0)
    ordn = OrdinalSpec(key="f", label="Finish", category="c", scale=["matte", "satin", "gloss"])
    assert "satin" in prompt(spec=ordn, current="matte")
    assert prompt(spec=OPEN_SPEC)  # open vocabulary has no list


def _strict(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
        for v in node.values():
            _strict(v)
    elif isinstance(node, list):
        for v in node:
            _strict(v)


def test_options_schema_is_strict() -> None:
    _strict(OPTIONS_SCHEMA)
    item = OPTIONS_SCHEMA["properties"]["options"]["items"]
    assert set(item["properties"]) == {"name", "description", "distance", "value", "keeps",
                                       "edit_prompt"}  # fmt: skip
    assert item["properties"]["distance"]["enum"] == ["near", "bold", "wild"]


def test_check_schema_is_strict() -> None:
    _strict(CHECK_SCHEMA)
    assert CHECK_SCHEMA["properties"]["answer"]["enum"] == ["yes", "no", "unclear"]
    assert CHECK_SCHEMA["properties"]["box"]["type"] == ["array", "null"]


def test_check_prompt_has_option() -> None:
    p = build_check_prompt(label="Markers", option_name="Devanagari numerals",
                           description="Hour markers in Devanagari")  # fmt: skip
    assert "Devanagari numerals" in p and "Markers" in p and "Hour markers" in p


def test_mock_explore_options_shape() -> None:
    out = MockReasoningProvider().explore_options([b"x"], "p")
    opts = out["options"]
    tag = opts[0]["name"].split()[-1]
    assert len(tag) == 4
    assert [o["name"] for o in opts] == [f"Option {c} {tag}" for c in "ABCDEFGH"]
    assert [o["distance"] for o in opts[:4]] == ["near", "bold", "wild", "near"]
    assert opts[0]["value"] == f"option_a_{tag}" and opts[7]["value"] == f"option_h_{tag}"
    assert all(o["keeps"] == [] and o["description"] and o["edit_prompt"] for o in opts)


def test_mock_check_target_shape() -> None:
    p = MockReasoningProvider(truth={"markers": "x"})
    assert p.check_target([b"x"], "p") == {"answer": "yes", "confidence": 0.9, "box": None,
                                           "note": ""}  # fmt: skip
    out = MockReasoningProvider().check_target([b"x"], "p")
    assert out["answer"] in ("yes", "no", "unclear") and 0 <= out["confidence"] <= 1


def test_mock_explore_options_vary_per_prompt() -> None:
    mock = MockReasoningProvider()
    first = [o["name"] for o in mock.explore_options([b"x"], "p")["options"]]
    again = [o["name"] for o in mock.explore_options([b"x"], "p")["options"]]
    other = [o["name"] for o in mock.explore_options([b"x"], "p, more")["options"]]
    assert first == again and not set(first) & set(other)
