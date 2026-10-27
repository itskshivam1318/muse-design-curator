from app.domain.kinds import (
    BooleanSpec,
    ColorSpec,
    EnumSpec,
    NumberSpec,
    OrdinalSpec,
    ShapeSpec,
    TextSpec,
)
from app.explore.service import coerce_option_value

ENUM = EnumSpec(key="markers", label="Markers", category="dial", vocabulary=["arabic", "roman"])


def test_enum_outside_vocab_is_kept_as_token() -> None:
    assert coerce_option_value(ENUM, "Devanagari Numerals", current="arabic") == (
        "devanagari_numerals"
    )
    assert coerce_option_value(ENUM, "roman", current="arabic") == "roman"
    assert coerce_option_value(ENUM, "  ", current="arabic") is None


def test_text_is_a_token() -> None:
    spec = TextSpec(key="style", label="Style", category="s")
    assert coerce_option_value(spec, "Quiet Utility", current=None) == "quiet_utility"


def test_number_inside_range_is_a_float_outside_is_none() -> None:
    spec = NumberSpec(key="d", label="Diameter", category="c", unit="mm", min=20, max=55,
                      tolerance=1)  # fmt: skip
    assert coerce_option_value(spec, "42", current=40.0) == 42.0
    assert coerce_option_value(spec, "80", current=40.0) is None
    assert coerce_option_value(spec, "big", current=40.0) is None
    assert coerce_option_value(spec, "nan", current=40.0) is None


def test_color_is_lowercased_name() -> None:
    spec = ColorSpec(key="c", label="Colour", category="c")
    assert coerce_option_value(spec, " Burnt Orange ", current="navy") == "burnt orange"
    assert coerce_option_value(spec, "", current="navy") is None


def test_ordinal_off_scale_is_none() -> None:
    spec = OrdinalSpec(key="f", label="Finish", category="c", scale=["matte", "satin", "gloss"])
    assert coerce_option_value(spec, "Satin", current="matte") == "satin"
    assert coerce_option_value(spec, "mirror", current="matte") is None


def test_boolean_flips_current() -> None:
    spec = BooleanSpec(key="has_date_window", label="Has date window", category="c")
    assert coerce_option_value(spec, "true", current=True) is False
    assert coerce_option_value(spec, "true", current=False) is True
    assert coerce_option_value(spec, "true", current=None) is None


def test_shape_is_none() -> None:
    spec = ShapeSpec(key="s", label="Silhouette", category="c", part="case")
    assert coerce_option_value(spec, "round", current=None) is None
