import numpy as np

from app.domain.kinds import (
    BooleanSpec,
    ColorSpec,
    EnumSpec,
    NumberSpec,
    OrdinalSpec,
    ShapeSpec,
    TextSpec,
)
from app.measure.palette import Lab
from app.measure.shape import shape_descriptor, shape_similarity
from app.retrieval.config import RANKING_CONFIG as CFG
from app.validation.comparators import AttrValue, compare


def av(value, conf=0.9, status="extracted", measured=None):
    return AttrValue(value, conf, status, measured)


ENUM = EnumSpec(key="e", label="E", category="c", vocabulary=["a", "b"])
ORD = OrdinalSpec(key="o", label="O", category="c", scale=["low", "mid", "high"])
NUM = NumberSpec(key="n", label="N", category="c", unit="x", min=0, max=10, tolerance=1.0)
BOOL = BooleanSpec(key="b", label="B", category="c")
COL = ColorSpec(key="k", label="K", category="c")
TXT = TextSpec(key="t", label="T", category="c")
SHP = ShapeSpec(key="s", label="S", category="c", part="p")


def lab(l: float) -> dict:
    return {"lab": [l, 0.0, 0.0]}


def test_config_values() -> None:
    d = CFG.model_dump()
    assert d["version"] == "rank-2026.10-c" and d["validated"] is False
    assert d["weights"] == {
        "target": 0.35,
        "preservation": 0.35,
        "relevance": 0.2,
        "diversity": 0.1,
    }
    assert d["relevance_mix"] == {"source_item": 0.6, "board_centroid": 0.4}
    assert (d["pool_size"], d["shortlist_size"], d["result_size"]) == (200, 16, 6)


def test_enum_equal_reliable_same_unequal_different() -> None:
    assert compare(ENUM, av("a"), av("a"), CFG) == "same"
    assert compare(ENUM, av("a"), av("b"), CFG) == "different"
    assert compare(BOOL, av(True), av(False), CFG) == "different"


def test_enum_low_confidence_unknown_but_edited_counts_reliable() -> None:
    assert compare(ENUM, av("a", 0.5, "uncertain"), av("a"), CFG) == "unknown"
    assert compare(ENUM, av("a", 0.5, "edited"), av("b"), CFG) == "different"
    assert compare(ENUM, av(None, 0.0, "missing"), av("a"), CFG) == "unknown"


def test_ordinal() -> None:
    assert compare(ORD, av("mid"), av("mid"), CFG) == "same"
    assert compare(ORD, av("mid"), av("high"), CFG) == "different"
    assert compare(ORD, av("mid", 0.5, "uncertain"), av("high"), CFG) == "unknown"


def test_number_within_tol_same_beyond_double_different_between_unknown() -> None:
    assert compare(NUM, av(5.0), av(5.8), CFG) == "same"
    assert compare(NUM, av(5.0), av(7.5), CFG) == "different"
    assert compare(NUM, av(5.0), av(6.5), CFG) == "unknown"
    assert compare(NUM, av(None, 0, "missing"), av(5.0), CFG) == "unknown"


def test_colour_delta_e_bands() -> None:
    assert compare(COL, av("x", measured=lab(50)), av("y", measured=lab(53)), CFG) == "same"
    assert compare(COL, av("x", measured=lab(50)), av("y", measured=lab(90)), CFG) == "different"
    a, b = lab(50), lab(50)
    from app.measure.palette import delta_e

    mid = next(v for v in np.arange(51, 80, 0.5) if 12 <= delta_e((50, 0, 0), (v, 0, 0)) <= 16)
    b = lab(float(mid))
    assert compare(COL, av("x", measured=a), av("y", measured=b), CFG) == "unknown"  # ΔE ~14
    assert compare(COL, av("x"), av("y", measured=a), CFG) == "unknown"


def _disc(r: int) -> dict:
    yy, xx = np.mgrid[:128, :128]
    return shape_descriptor(((yy - 64) ** 2 + (xx - 64) ** 2) <= r * r)


def _bar() -> dict:
    m = np.zeros((128, 128), bool)
    m[56:72, 8:120] = True
    return shape_descriptor(m)


def test_shape_bands() -> None:
    d1, d2, bar = _disc(40), _disc(41), _bar()
    assert shape_similarity(d1, d2) >= 0.85
    assert compare(SHP, av(None, measured=d1), av(None, measured=d2), CFG) == "same"
    assert shape_similarity(d1, bar) <= 0.60
    assert compare(SHP, av(None, measured=d1), av(None, measured=bar), CFG) == "different"
    assert compare(SHP, av(None), av(None, measured=d1), CFG) == "unknown"


def test_shape_similarity_between_bands_is_unknown(monkeypatch) -> None:
    import app.validation.comparators as mod

    monkeypatch.setattr(mod, "shape_similarity", lambda a, b: 0.7)
    d = _disc(40)
    assert compare(SHP, av(None, measured=d), av(None, measured=d), CFG) == "unknown"


def test_text_always_unknown() -> None:
    assert compare(TXT, av("same"), av("same"), CFG) == "unknown"


def test_attrvalue_constructors() -> None:
    from types import SimpleNamespace

    from app.domain.attributes import AttributeRecord

    row = SimpleNamespace(value_json="a", confidence=0.8, measured_json={"lab": [1, 2, 3]})
    v = AttrValue.from_row(row)
    assert (v.value, v.confidence, v.measured) == ("a", 0.8, {"lab": [1, 2, 3]})
    rec = AttributeRecord(
        key="e", label="E", category="c", kind="enum", value="a", confidence=0.5,
        status="confirmed", source="user",
    )  # fmt: skip
    assert AttrValue.from_record(rec).status == "confirmed"
    assert Lab  # re-exported type
