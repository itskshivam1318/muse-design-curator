"""Separate target / preservation / relevance scores for a candidate (all 0..1)."""

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from app.domain.kinds import AttributeSpec
from app.domain.variation import VariationSpec, number_step
from app.measure.palette import delta_e
from app.retrieval.config import RANKING_CONFIG, RankingConfig
from app.retrieval.filters import value_verdict
from app.retrieval.pool import PoolItem
from app.validation.comparators import AttrValue, compare


@dataclass(frozen=True)
class Scores:
    target: float
    preservation: float
    relevance: float
    diversity: float
    total: float


@dataclass
class Candidate:
    pool: PoolItem
    scores: Scores
    rank: int | None = None


def total_score(s: Scores, cfg: RankingConfig) -> float:
    w = cfg.weights
    return (
        w.target * s.target
        + w.preservation * s.preservation
        + w.relevance * s.relevance
        + w.diversity * s.diversity
    )


def relevance_score(cos: float) -> float:
    return min(1.0, max(0.0, (cos + 1.0) / 2.0))


def _partial(cand: AttrValue | None) -> float:
    """Credit for a value that cannot be judged same or different: half its confidence."""
    if cand is None or cand.value is None:
        return 0.0
    return 0.5 * cand.confidence


def _lab(v: AttrValue) -> list[float] | None:
    lab = (v.measured or {}).get("lab")
    return lab if lab is not None and len(lab) == 3 else None


def _explore(spec: AttributeSpec, src: AttrValue, cand: AttrValue, cfg: RankingConfig) -> float:
    verdict = compare(spec, src, cand, cfg)
    if verdict == "different":
        return 1.0
    if verdict == "same":
        return 0.0
    if spec.kind == "color":
        a, b = _lab(src), _lab(cand)
        if a is not None and b is not None:
            de = delta_e(tuple(a), tuple(b))  # type: ignore[arg-type]
            if cfg.color_same_max <= de < cfg.color_different_min:
                span = cfg.color_different_min - cfg.color_same_max
                return 0.5 * (de - cfg.color_same_max) / span
    return _partial(cand)


def nudge_position(
    spec: VariationSpec, cand: AttrValue, cfg: RankingConfig
) -> Literal["exact", "beyond", "near", "off"] | None:
    """Where a candidate sits against the requested nudge; None when it cannot be judged.

    exact: the requested position; beyond: one step further in the same direction;
    near: a number within twice the tolerance of the request; off: anywhere else.
    """
    tspec, nudge = spec.target_spec, spec.request.nudge
    if nudge is None or spec.target_value is None or cand.value is None:
        return None
    sign = 1 if nudge.direction == "more" else -1
    if tspec.kind == "ordinal":
        scale = tspec.scale  # type: ignore[union-attr]
        if not cand.reliable(cfg) or cand.value not in scale or spec.target_value not in scale:
            return None
        base, idx = scale.index(str(spec.target_value)), scale.index(str(cand.value))
        want = base + sign * nudge.steps
        return "exact" if idx == want else "beyond" if idx == want + sign else "off"
    if tspec.kind == "number":
        if isinstance(cand.value, bool | str) or isinstance(spec.target_value, bool | str):
            return None
        tol, step = tspec.tolerance, number_step(tspec)  # type: ignore[union-attr]
        want_v = float(spec.target_value) + sign * nudge.steps * step
        x = float(cand.value)
        if abs(x - want_v) <= tol:
            return "exact"
        if abs(x - (want_v + sign * step)) <= tol:
            return "beyond"
        return "near" if abs(x - want_v) <= 2 * tol else "off"
    return None


def _nudge(spec: VariationSpec, cand: AttrValue, cfg: RankingConfig) -> float:
    pos = nudge_position(spec, cand, cfg)
    return 1.0 if pos == "exact" else 0.5 if pos == "beyond" else 0.0


def target_score(
    spec: VariationSpec,
    source_attr: AttrValue | None,
    cand_attr: AttrValue | None,
    cfg: RankingConfig,
) -> float:
    mode, tspec = spec.request.mode, spec.target_spec
    if cand_attr is None or cand_attr.value is None:
        return 0.0
    if mode == "explore":
        src = source_attr or AttrValue(spec.target_value, 1.0, "confirmed")
        return _explore(tspec, src, cand_attr, cfg)
    if mode == "nudge":
        return _nudge(spec, cand_attr, cfg)
    verdicts = [value_verdict(tspec, cand_attr, v, cfg) for v in spec.values]
    if mode == "prefer":
        if "same" in verdicts:
            return 1.0
    else:  # avoid
        if "same" in verdicts:
            return 0.0
        if all(v == "different" for v in verdicts):
            return 1.0
    return _partial(cand_attr) if "unknown" in verdicts else 0.0


def preservation_score(
    spec: VariationSpec,
    source_attrs: dict[str, AttrValue],
    cand_attrs: dict[str, AttrValue],
    cfg: RankingConfig,
) -> float:
    if not spec.protected:
        return 1.0
    total = 0.0
    for prot in spec.protected:
        cand = cand_attrs.get(prot.key)
        if cand is None or cand.value is None:
            continue
        src = source_attrs.get(prot.key) or AttrValue(prot.value, 1.0, "confirmed")
        verdict = compare(prot.spec, cand, src, cfg)
        total += 1.0 if verdict == "same" else _partial(cand) if verdict == "unknown" else 0.0
    return total / len(spec.protected)


def score_candidate(
    p: PoolItem, spec: VariationSpec, source_attrs: dict[str, AttrValue], cfg: RankingConfig
) -> Candidate:
    key = spec.target_spec.key
    s = Scores(
        target=target_score(spec, source_attrs.get(key), p.attrs.get(key), cfg),
        preservation=preservation_score(spec, source_attrs, p.attrs, cfg),
        relevance=relevance_score(p.relevance),
        diversity=1.0,
        total=0.0,
    )
    return Candidate(p, replace(s, total=total_score(s, cfg)))


def _cos(a: object, b: object) -> float:
    if a is None or b is None:
        return 0.0
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(x @ y) / n if n else 0.0


def pair_similarity(
    a: PoolItem, b: PoolItem, spec: VariationSpec, cfg: RankingConfig = RANKING_CONFIG
) -> float:
    key = spec.target_spec.key
    ta, tb = a.attrs.get(key), b.attrs.get(key)
    same = ta is not None and tb is not None and compare(spec.target_spec, ta, tb, cfg) == "same"
    sim = 0.5 * _cos(a.embedding, b.embedding) + 0.5 * (1.0 if same else 0.0)
    return min(1.0, max(0.0, sim))  # opposite embeddings must not push diversity above 1
