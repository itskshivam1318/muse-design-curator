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
