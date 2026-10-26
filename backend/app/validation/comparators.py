"""Per-kind comparison of two attribute values: same, different, or unknown (never a guess)."""

from dataclasses import dataclass
from typing import Any, Literal

from app.domain.attributes import AttributeRecord, Value
from app.domain.kinds import AttributeSpec
from app.measure.palette import delta_e
from app.measure.shape import shape_similarity
from app.retrieval.config import RankingConfig

Verdict = Literal["same", "different", "unknown"]
TRUSTED_STATUSES = ("edited", "confirmed")


@dataclass(frozen=True)
class AttrValue:
    value: Value
    confidence: float
    status: str
    measured: dict[str, Any] | None = None

    @classmethod
    def from_record(cls, rec: AttributeRecord) -> "AttrValue":
        return cls(rec.value, rec.confidence, rec.status, rec.measured)

    @classmethod
    def from_row(cls, row: Any) -> "AttrValue":
        """From a `corpus_attributes` row (value_json, confidence, measured_json)."""
        return cls(row.value_json, float(row.confidence), "extracted", row.measured_json)

    def reliable(self, cfg: RankingConfig) -> bool:
        if self.value is None:
            return False
        return self.confidence >= cfg.reliable_confidence or self.status in TRUSTED_STATUSES


def _lab(v: AttrValue) -> list[float] | None:
    lab = (v.measured or {}).get("lab")
    return lab if lab is not None and len(lab) == 3 else None


def _number(v: AttrValue) -> float | None:
    if v.value is None or isinstance(v.value, bool | str):
        return None
    return float(v.value)


def compare(spec: AttributeSpec, a: AttrValue, b: AttrValue, cfg: RankingConfig) -> Verdict:
    kind = spec.kind
    if kind == "text":
        return "unknown"
    if kind in ("enum", "boolean"):
        if not (a.reliable(cfg) and b.reliable(cfg)):
            return "unknown"
        return "same" if a.value == b.value else "different"
    if kind == "ordinal":
        if not (a.reliable(cfg) and b.reliable(cfg)):
            return "unknown"
        scale = spec.scale  # type: ignore[union-attr]
        if not isinstance(a.value, str) or not isinstance(b.value, str):
            return "unknown"
        if a.value not in scale or b.value not in scale:
            return "unknown"
        return "same" if scale.index(a.value) == scale.index(b.value) else "different"
    if kind == "number":
        x, y = _number(a), _number(b)
        if x is None or y is None:
            return "unknown"
        tol = spec.tolerance  # type: ignore[union-attr]
        d = abs(x - y)
        if d <= tol:
            return "same"
        return "different" if d > 2 * tol else "unknown"
    if kind == "color":
        la, lb = _lab(a), _lab(b)
        if la is None or lb is None:
            return "unknown"
        de = delta_e(tuple(la), tuple(lb))  # type: ignore[arg-type]
        if de <= cfg.color_same_max:
            return "same"
        return "different" if de >= cfg.color_different_min else "unknown"
    if kind == "shape":
        ma, mb = a.measured, b.measured
        if not ma or not mb or "hu" not in ma or "hu" not in mb:
            return "unknown"
        sim = shape_similarity(ma, mb)
        if sim >= cfg.shape_same_min:
            return "same"
        return "different" if sim <= cfg.shape_different_max else "unknown"
    return "unknown"
