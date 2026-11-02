from app.analysis.spec import dimension_type, spec_for, spec_from_dimension
from app.analysis.types import DimensionOut
from app.db.models import ItemAttribute
from app.domain.kinds import EnumSpec, NumberSpec, TextSpec
from app.domain.lens import LensSpec


def _row(**kw):
    base = {"key": "mood", "label": "Mood", "category": "feel", "kind": "text"}
    return ItemAttribute(**{**base, **kw})


def test_spec_for_prefers_stored_spec():
    stored = EnumSpec(key="mood", label="Mood", category="feel", vocabulary=["calm", "tense"])
    row = _row(spec_json=stored.model_dump())
    spec = spec_for(row)
    assert spec.kind == "enum" and spec.vocabulary == ["calm", "tense"]


def test_spec_for_falls_back_to_lens_then_text():
    lens_attr = EnumSpec(key="mood", label="Lens mood", category="c", vocabulary=["a"])
    lens = LensSpec(
        id="x@1", domain="x", label="X", origin="curated", parts=[], attributes=[lens_attr]
    )
    assert spec_for(_row(), lens).label == "Lens mood"
    fallback = spec_for(_row(key="other"), lens)
    assert isinstance(fallback, TextSpec) and fallback.category == "feel"
    assert isinstance(spec_for(_row()), TextSpec)


def _dim(**kw):
    base = {
        "key": "formality",
        "label": "Formality",
        "type": "abstract",
        "prompt": "How formal?",
        "kind": "ordinal",
        "value": "mid",
        "confidence": 0.7,
    }
    return DimensionOut(**{**base, **kw})


def test_spec_from_dimension_ordinal_keeps_scale():
    d = _dim(scale=["low", "mid", "high"])
    assert spec_from_dimension(d).scale == ["low", "mid", "high"]


def test_spec_from_dimension_enum_is_open_and_number_has_range():
    e = spec_from_dimension(_dim(kind="enum", vocabulary=["a", "b"]))
    assert e.open_vocabulary and e.vocabulary == ["a", "b"]
    n = spec_from_dimension(_dim(kind="number", min=0, max=10, unit="cm"))
    assert isinstance(n, NumberSpec) and n.unit == "cm" and n.tolerance == 0.5
    p = spec_from_dimension(_dim(kind="shape", type="physical", part="roof", prompt=None))
    assert p.part == "roof"


def test_dimension_type():
    assert dimension_type(_row(dim_type="physical")) == "physical"
    assert dimension_type(_row(dim_type="abstract")) == "abstract"
