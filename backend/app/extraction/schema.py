"""JSON schema the reasoning provider fills in, built from the lens."""

from typing import Any

from app.domain.kinds import AttributeSpec, NumberSpec

_EVIDENCE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["region", "cue", "none"]},
        "bbox": {
            "type": ["array", "null"],
            "items": {"type": "number", "minimum": 0, "maximum": 1},
            "minItems": 4,
            "maxItems": 4,
        },
        "note": {"type": ["string", "null"]},
    },
    "required": ["kind", "bbox", "note"],
    "additionalProperties": False,  # strict structured output: every object is closed
}


def is_measured(spec: AttributeSpec) -> bool:
    """Attributes computed by code, never asked of the model."""
    if spec.kind in ("color", "shape"):
        return True
    return isinstance(spec, NumberSpec) and spec.measure != "model"


def model_specs(attributes: list[AttributeSpec]) -> list[AttributeSpec]:
    return [a for a in attributes if not is_measured(a)]


def _value_schema(spec: AttributeSpec) -> dict[str, Any]:
    if spec.kind == "ordinal":
        return {"type": ["string", "null"], "enum": [*spec.scale, None]}
    if spec.kind == "enum":
        if spec.open_vocabulary or not spec.vocabulary:
            return {"type": ["string", "null"]}
        return {"type": ["string", "null"], "enum": [*spec.vocabulary, None]}
    if spec.kind == "number":
        return {"type": ["number", "null"], "minimum": spec.min, "maximum": spec.max}
    if spec.kind == "boolean":
        return {"type": ["boolean", "null"]}
    return {"type": ["string", "null"]}


def build_extraction_schema(lens: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for spec in model_specs(lens.attributes):
        where = f" Look at the {spec.part}." if spec.part else ""
        props[spec.key] = {
            "type": "object",
            "description": f"{spec.label}.{where} Use null when it cannot be seen.",
            "properties": {
                "value": _value_schema(spec),
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "evidence": _EVIDENCE,
            },
            "required": ["value", "confidence", "evidence"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }
