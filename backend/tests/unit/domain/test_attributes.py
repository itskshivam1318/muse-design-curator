from pydantic import TypeAdapter

from app.domain.attributes import Evidence, ModelAttribute, normalize_model_attribute
from app.domain.kinds import AttributeSpec

adapter = TypeAdapter(AttributeSpec)
BASE = {"key": "k_one", "label": "K", "category": "c"}
REGION = Evidence(kind="region", bbox=(0.1, 0.1, 0.5, 0.5))


def spec(**extra):  # type: ignore[no-untyped-def]
    return adapter.validate_python({**BASE, **extra})


def norm(value, s, conf=0.9, evidence=REGION):  # type: ignore[no-untyped-def]
    raw = ModelAttribute(key="k_one", value=value, confidence=conf, evidence=evidence)
    return normalize_model_attribute(raw, s, "model", "test")


def test_ordinal_outside_scale_is_missing() -> None:
    s = spec(kind="ordinal", scale=["low", "mid", "high"])
    assert norm("mid", s).value == "mid"
    r = norm("huge", s)
    assert r.value is None and r.status == "missing"


def test_number_outside_range_is_missing() -> None:
    s = spec(kind="number", unit="mm", min=20, max=55, tolerance=1.5)
    assert norm(40, s).value == 40.0
    r = norm(80, s)
    assert r.value is None and r.status == "missing"


def test_boolean_accepts_only_true_false() -> None:
    s = spec(kind="boolean")
    assert norm(True, s).value is True
    assert norm("false", s).value is False
    r = norm("maybe", s)
    assert r.value is None and r.status == "missing"
    assert norm(1.0, s).status == "missing"


def test_closed_vocabulary_rejects_unknown() -> None:
    s = spec(kind="enum", vocabulary=["round", "square"])
    assert norm("Round", s).value == "round"
    assert norm("hexagon", s).status == "missing"


def test_open_vocabulary_canonicalised_and_kept() -> None:
    s = spec(kind="enum", open_vocabulary=True)
    r = norm("  Rose-Gold Plated ", s)
    assert r.value == "rose_gold_plated" and r.status == "extracted"


def test_no_evidence_is_missing_even_at_high_confidence() -> None:
    s = spec(kind="text")
    r = norm("x", s, conf=0.95, evidence=Evidence(kind="none"))
    assert r.value is None and r.status == "missing"


def test_low_confidence_is_missing() -> None:
    assert norm("x", spec(kind="text"), conf=0.39).status == "missing"


def test_mid_confidence_is_uncertain() -> None:
    r = norm("x", spec(kind="text"), conf=0.55)
    assert r.status == "uncertain" and r.value == "x"


def test_high_confidence_with_region_is_extracted() -> None:
    r = norm("x", spec(kind="text"), conf=0.82)
    assert r.status == "extracted" and r.value == "x"
    assert r.source == "model" and r.source_detail == "test" and r.enabled is True


def test_bool_is_not_a_valid_value_for_text_color_number_or_enum() -> None:
    from app.domain.attributes import validate_value

    for s in (
        spec(kind="text"),
        spec(kind="color"),
        spec(kind="number", unit="mm", min=0, max=5, tolerance=1),
        spec(kind="enum", open_vocabulary=True),
        spec(kind="ordinal", scale=["a", "b", "c"]),
    ):
        assert validate_value(True, s) is None
        assert validate_value(False, s) is None
    assert validate_value(True, spec(kind="boolean")) is True
