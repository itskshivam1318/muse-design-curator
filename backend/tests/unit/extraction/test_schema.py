from app.domain.lens import LensSpec
from app.extraction.schema import build_extraction_schema

LENS = LensSpec.model_validate({
    "id": "thing@1", "domain": "thing", "label": "Thing", "origin": "edited",
    "parts": [{"id": "body", "sam_prompt": "body"}],
    "attributes": [
        {"key": "weight", "label": "W", "category": "c", "kind": "ordinal",
         "scale": ["light", "mid", "heavy"]},
        {"key": "tone", "label": "T", "category": "c", "kind": "enum", "vocabulary": ["a", "b"]},
        {"key": "style", "label": "S", "category": "c", "kind": "enum", "open_vocabulary": True},
        {"key": "size", "label": "Z", "category": "c", "kind": "number", "unit": "mm",
         "min": 10, "max": 90, "tolerance": 2},
        {"key": "cover", "label": "C", "category": "c", "kind": "number", "unit": "r",
         "min": 0, "max": 1, "tolerance": 0.1, "measure": "mask_ratio", "part": "body"},
        {"key": "hue", "label": "H", "category": "c", "kind": "color", "part": "body"},
        {"key": "logo", "label": "L", "category": "c", "kind": "boolean"},
        {"key": "summary", "label": "Y", "category": "c", "kind": "text"},
    ],
})  # fmt: skip


def _value(key: str) -> dict:
    return build_extraction_schema(LENS)["properties"][key]["properties"]["value"]


def test_ordinal_is_enum_of_scale_plus_null() -> None:
    v = _value("weight")
    assert v["type"] == ["string", "null"] and v["enum"] == ["light", "mid", "heavy", None]


def test_closed_enum_and_open_enum() -> None:
    assert _value("tone")["enum"] == ["a", "b", None]
    assert _value("style") == {"type": ["string", "null"]}


def test_number_has_min_max() -> None:
    v = _value("size")
    assert v == {"type": ["number", "null"], "minimum": 10, "maximum": 90}


def test_boolean_and_text() -> None:
    assert _value("logo") == {"type": ["boolean", "null"]}
    assert _value("summary") == {"type": ["string", "null"]}


def test_measured_attributes_are_not_asked_of_the_model() -> None:
    props = build_extraction_schema(LENS)["properties"]
    assert set(props) == {"weight", "tone", "style", "size", "logo", "summary"}


def test_each_attribute_wrapped_with_confidence_and_evidence() -> None:
    p = build_extraction_schema(LENS)["properties"]["logo"]
    assert set(p["properties"]) == {"value", "confidence", "evidence"}
    assert p["properties"]["confidence"]["minimum"] == 0
    ev = p["properties"]["evidence"]["properties"]
    assert ev["kind"]["enum"] == ["region", "cue", "none"] and "bbox" in ev and "note" in ev
