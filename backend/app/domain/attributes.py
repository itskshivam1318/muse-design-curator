import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.kinds import AttributeSpec

RELIABLE_CONFIDENCE = 0.7
MIN_CONFIDENCE = 0.4

Kind = Literal["enum", "ordinal", "number", "boolean", "color", "text", "shape"]
Status = Literal["extracted", "uncertain", "missing", "edited", "confirmed"]
Source = Literal["model", "mock", "user", "corpus_index", "measured", "plugin"]
Value = str | float | bool | None


class Evidence(BaseModel):
    kind: Literal["region", "cue", "measurement", "none"] = "none"
    bbox: tuple[float, float, float, float] | None = None
    note: str | None = None

    def model_post_init(self, _ctx: Any) -> None:
        if self.bbox is not None and not all(0 <= c <= 1 for c in self.bbox):
            raise ValueError("bbox coordinates must be within 0..1")


class ModelAttribute(BaseModel):
    key: str
    value: Value = None
    confidence: float = Field(ge=0, le=1)
    evidence: Evidence = Field(default_factory=Evidence)


class AttributeRecord(BaseModel):
    key: str
    label: str
    category: str
    kind: Kind
    part: str | None = None
    value: Value = None
    confidence: float = Field(ge=0, le=1)
    status: Status
    source: Source
    source_detail: str = ""
    evidence: Evidence = Field(default_factory=Evidence)
    enabled: bool = True
    measured: dict[str, Any] | None = None


def canonical_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _coerce_bool(value: Value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _coerce_number(value: Value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def validate_value(raw: Value, spec: AttributeSpec) -> Value:
    """Return the cleaned value, or None when it does not fit the spec."""
    if raw is None:
        return None
    if isinstance(raw, bool) and spec.kind != "boolean":
        return None
    if spec.kind == "boolean":
        return _coerce_bool(raw)
    if spec.kind == "number":
        num = _coerce_number(raw)
        if num is None or not spec.min <= num <= spec.max:
            return None
        return num
    if not isinstance(raw, str) or not raw.strip():
        return None
    if spec.kind == "ordinal":
        token = canonical_token(raw)
        return token if token in spec.scale else None
    if spec.kind == "enum":
        token = canonical_token(raw)
        if spec.vocabulary is not None and token in spec.vocabulary:
            return token
        if spec.open_vocabulary and token:
            return token
        return None
    return raw.strip()


def normalize_model_attribute(
    raw: ModelAttribute, spec: AttributeSpec, source: str, source_detail: str
) -> AttributeRecord:
    value = validate_value(raw.value, spec)
    if raw.evidence.kind == "none" or raw.confidence < MIN_CONFIDENCE or value is None:
        value, status = None, "missing"
    elif raw.confidence < RELIABLE_CONFIDENCE:
        status = "uncertain"
    else:
        status = "extracted"
    return AttributeRecord.model_validate(
        {
            "key": spec.key,
            "label": spec.label,
            "category": spec.category,
            "kind": spec.kind,
            "part": spec.part,
            "value": value,
            "confidence": raw.confidence,
            "status": status,
            "source": source,
            "source_detail": source_detail,
            "evidence": raw.evidence,
        }
    )
