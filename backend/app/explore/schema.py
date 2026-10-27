"""Strict JSON schemas for Muse Spark's explore and check answers."""

from typing import Any

OPTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["options"],
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "description", "distance", "value", "keeps", "edit_prompt"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "distance": {"type": "string", "enum": ["near", "bold", "wild"]},
                    "value": {"type": "string"},
                    "keeps": {"type": "array", "items": {"type": "string"}},
                    "edit_prompt": {"type": "string"},
                },
            },
        }
    },
}

CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "confidence", "box", "note"],
    "properties": {
        "answer": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "confidence": {"type": "number"},
        # [x0, y0, x1, y1], each 0..1, around the part that answers the question
        "box": {"type": ["array", "null"], "items": {"type": "number"}},
        "note": {"type": "string"},
    },
}
