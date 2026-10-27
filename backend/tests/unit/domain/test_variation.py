from types import SimpleNamespace
from typing import Any

import pytest

from app.board.profile import BoardProfile, Signal
from app.domain.attributes import AttributeRecord
from app.domain.lens import LensSpec
from app.domain.variation import (
    VariationRequest,
    VariationSpec,
    propose_protected,
    validate_variation,
)
from app.errors import AppError

LENS = LensSpec.model_validate(
    {
        "id": "demo@1",
        "domain": "demo",
        "label": "Demo",
        "origin": "curated",
        "parts": [],
        "attributes": [
            {
                "key": "style",
                "label": "Style",
                "category": "c",
                "kind": "enum",
                "vocabulary": ["a_b", "c"],
            },
            {
                "key": "weight",
                "label": "Weight",
                "category": "c",
                "kind": "ordinal",
                "scale": ["low", "mid", "high"],
            },
            {
                "key": "size",
                "label": "Size",
                "category": "c",
                "kind": "number",
                "unit": "mm",
                "min": 10,
                "max": 50,
                "tolerance": 2,
            },
            {"key": "tone", "label": "Tone", "category": "c", "kind": "color"},
            {"key": "flag", "label": "Flag", "category": "c", "kind": "boolean"},
            {"key": "note", "label": "Note", "category": "c", "kind": "text"},
        ],
    }
)
VALUES: dict[str, Any] = {
    "style": "a_b",
    "weight": "mid",
    "size": 30.0,
    "tone": "black",
    "flag": True,
    "note": "x",
}
ITEM = SimpleNamespace(role="reference")


def attrs(**over: Any) -> list[AttributeRecord]:
    vals = {**VALUES, **over}
    out = []
    for s in LENS.attributes:
        v = vals.get(s.key)
        out.append(
            AttributeRecord(
                key=s.key,
                label=s.label,
                category="c",
                kind=s.kind,
                value=v,
                confidence=0.9,
                status="missing" if v is None else "extracted",
                source="model",
            )
        )
    return out


def req(**kw: Any) -> VariationRequest:
    base: dict[str, Any] = {"source_item_id": "i1", "target_key": "style", "mode": "explore"}
    return VariationRequest.model_validate({**base, **kw})


def code(r: VariationRequest, a: list[AttributeRecord] | None = None, item: Any = ITEM) -> str:
    with pytest.raises(AppError) as e:
        validate_variation(r, item, a or attrs(), LENS)
    assert e.value.status == 422
    assert e.value.details
    return e.value.code


def test_valid_and_empty_protected() -> None:
    spec = validate_variation(req(), ITEM, attrs(), LENS)
    assert isinstance(spec, VariationSpec)
    assert spec.target_value == "a_b" and spec.protected == ()
    spec = validate_variation(req(protected_keys=["weight"]), ITEM, attrs(), LENS)
    assert spec.protected[0].value == "mid"


def test_keys_validated_against_lens() -> None:
    assert code(req(target_key="nope")) == "UNKNOWN_ATTRIBUTE"
    assert code(req(protected_keys=["nope"])) == "UNKNOWN_ATTRIBUTE"


def test_conflicts() -> None:
    assert code(req(protected_keys=["weight", "weight"])) == "DUPLICATE_PROTECTED_KEY"
    assert code(req(protected_keys=["style"])) == "TARGET_PROTECTED_CONFLICT"


def test_counter_example() -> None:
    assert code(req(), item=SimpleNamespace(role="counter_example")) == "SOURCE_IS_COUNTER_EXAMPLE"


def test_disabled() -> None:
    a = attrs()
    a[0] = a[0].model_copy(update={"enabled": False})
    assert code(req(), a) == "TARGET_DISABLED"
    a = attrs()
    a[1] = a[1].model_copy(update={"enabled": False})
    assert code(req(protected_keys=["weight"]), a) == "PROTECTED_DISABLED"


def test_values_shape() -> None:
    assert code(req(mode="prefer")) == "TARGET_VALUES_REQUIRED"
    assert code(req(mode="avoid")) == "TARGET_VALUES_REQUIRED"
    assert code(req(target_values=["c"])) == "TARGET_VALUES_NOT_ALLOWED"
    assert code(
        req(
            mode="nudge",
            target_key="weight",
            target_values=["low"],
            nudge={"direction": "more", "steps": 1},
        )
    ) == ("TARGET_VALUES_NOT_ALLOWED")


def test_value_invalid_and_prefer_current() -> None:
    assert code(req(mode="prefer", target_values=["zzz"])) == "TARGET_VALUE_INVALID"
    assert (
        code(req(mode="prefer", target_key="size", target_values=["99"])) == "TARGET_VALUE_INVALID"
    )
    assert (
        code(req(mode="prefer", target_key="tone", target_values=["notacolour"]))
        == "TARGET_VALUE_INVALID"
    )
    ok = validate_variation(
        req(mode="prefer", target_key="tone", target_values=["White"]), ITEM, attrs(), LENS
    )
    assert ok.values == ("white",)
    assert code(req(mode="prefer", target_values=["a_b"])) == "PREFER_EQUALS_CURRENT"
    validate_variation(req(mode="avoid", target_values=["a_b"]), ITEM, attrs(), LENS)


def test_known_value_checks() -> None:
    assert code(req(), attrs(style=None)) == "EXPLORE_NEEDS_KNOWN_TARGET"
    assert code(req(protected_keys=["weight"]), attrs(weight=None)) == "PROTECTED_VALUE_UNKNOWN"


def test_nudge() -> None:
    n = {"direction": "more", "steps": 1}
    assert code(req(mode="nudge")) == "NUDGE_PARAMS_REQUIRED"
    assert code(req(nudge=n)) == "NUDGE_PARAMS_REQUIRED"
    assert code(req(mode="nudge", target_key="style", nudge=n)) == "NUDGE_NOT_SUPPORTED"
    assert (
        code(req(mode="nudge", target_key="weight", nudge=n), attrs(weight=None))
        == "NUDGE_NEEDS_KNOWN_TARGET"
    )
    assert (
        code(req(mode="nudge", target_key="weight", nudge={"direction": "more", "steps": 2}))
        == "NUDGE_OUT_OF_RANGE"
    )
    validate_variation(req(mode="nudge", target_key="weight", nudge=n), ITEM, attrs(), LENS)
    # number step = 2 x tolerance = 4
    validate_variation(
        req(mode="nudge", target_key="size", nudge={"direction": "more", "steps": 2}),
        ITEM,
        attrs(size=40.0),
        LENS,
    )
    assert (
        code(
            req(mode="nudge", target_key="size", nudge={"direction": "more", "steps": 2}),
            attrs(size=44.0),
        )
        == "NUDGE_OUT_OF_RANGE"
    )


def test_propose_protected_orders_signals_first_and_excludes() -> None:
    a = attrs(note=None)
    a[4] = a[4].model_copy(update={"enabled": False})  # flag disabled
    sig = lambda k, c: Signal(key=k, label=k, kind="x", modal_value="v", consistency=c, n_known=3)
    profile = BoardProfile(signals=[sig("tone", 0.7), sig("size", 0.9), sig("style", 1.0)])
    out = propose_protected(a, "style", profile)
    assert [r["key"] for r in out] == ["size", "tone", "weight"]
    assert out[0] == {"key": "size", "is_board_signal": True, "strength": 0.9}
    assert out[2] == {"key": "weight", "is_board_signal": False, "strength": 0.0}
    assert [r["key"] for r in propose_protected(a, "style", None)] == ["weight", "size", "tone"]


def test_ordinal_nudge_edges() -> None:
    less = {"direction": "less", "steps": 1}
    r = req(mode="nudge", target_key="weight", nudge=less)
    assert code(r, attrs(weight="low")) == "NUDGE_OUT_OF_RANGE"
    # a stored value outside the scale is a 422, not a ValueError
    assert code(r, attrs(weight="bogus")) == "NUDGE_NEEDS_KNOWN_TARGET"
