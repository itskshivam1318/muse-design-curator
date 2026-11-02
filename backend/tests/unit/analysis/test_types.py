import pytest
from pydantic import ValidationError

from app.analysis.types import ANALYSIS_SCHEMA, Analysis, DimensionOut, Region
from app.providers.reasoning import strict_schema


def _dim(**kw):
    base = {
        "key": "mood",
        "label": "Mood",
        "type": "abstract",
        "prompt": "What mood?",
        "kind": "text",
        "value": "calm",
        "confidence": 0.8,
    }
    return DimensionOut(**{**base, **kw})


def test_physical_needs_part_abstract_needs_prompt():
    with pytest.raises(ValidationError):
        _dim(type="physical", part=None)
    with pytest.raises(ValidationError):
        _dim(type="abstract", part="roof")
    with pytest.raises(ValidationError):
        _dim(type="abstract", prompt=None)
    assert _dim(type="physical", part="roof", prompt=None).part == "roof"


def test_region_validation():
    assert Region(kind="box", box=[0, 0, 1, 0.5]).box == [0, 0, 1, 0.5]
    with pytest.raises(ValidationError):
        Region(kind="box", box=[0, 0, 2, 1])
    with pytest.raises(ValidationError):
        Region(kind="text_range", range=[5, 5])


def test_analysis_limits():
    ok = {"content_type": "image", "summary": "s", "parts": [], "dimensions": []}
    assert Analysis(**ok)
    parts = [{"key": f"p{i}", "label": "p", "region_kind": "box"} for i in range(9)]
    with pytest.raises(ValidationError):
        Analysis(**{**ok, "parts": parts})


def test_analysis_schema_is_strict():
    assert strict_schema(ANALYSIS_SCHEMA) == ANALYSIS_SCHEMA
    assert ANALYSIS_SCHEMA["title"] == "item_analysis"
    assert ANALYSIS_SCHEMA["properties"]["parts"]["maxItems"] == 8
    assert ANALYSIS_SCHEMA["properties"]["dimensions"]["maxItems"] == 20


def test_kind_specific_requirements_rejected_up_front():
    with pytest.raises(ValidationError):
        _dim(kind="ordinal", scale=["low", "high"])
    with pytest.raises(ValidationError):
        _dim(kind="ordinal", scale=["low", "mid", "mid"])
    with pytest.raises(ValidationError):
        _dim(kind="number", min=5, max=5)
    with pytest.raises(ValidationError):
        _dim(kind="number", min=None, max=None)
    with pytest.raises(ValidationError):
        _dim(kind="enum", vocabulary=["Not Canonical"])
    with pytest.raises(ValidationError):
        _dim(kind="shape")  # abstract shape has no part


def test_spec_from_dimension_total_for_every_valid_kind():
    from app.analysis.spec import spec_from_dimension

    valid = [
        _dim(kind="enum", vocabulary=["a", "b"]),
        _dim(kind="enum"),
        _dim(kind="ordinal", scale=["low", "mid", "high"]),
        _dim(kind="number", min=0, max=10, unit="cm"),
        _dim(kind="boolean"),
        _dim(kind="color"),
        _dim(kind="text"),
        _dim(kind="shape", type="physical", part="roof", prompt=None),
    ]
    assert [spec_from_dimension(d).kind for d in valid] == [
        "enum",
        "enum",
        "ordinal",
        "number",
        "boolean",
        "color",
        "text",
        "shape",
    ]
