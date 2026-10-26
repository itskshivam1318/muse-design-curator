"""Deterministic run summary and shortfall messages, worded with the lens's labels."""

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import RunCandidate, VariationRun
from app.db.repos import runs as runs_repo
from app.domain.lens import LensSpec
from app.retrieval.config import RankingConfig

SHORTFALL_ORDER = (
    "protected_changed", "target_not_met", "uncertain", "no_target_change", "avoided_value",
    "on_board", "duplicate_source", "duplicate_other", "provenance", "unusable", "no_candidates",
)  # fmt: skip


def _labels(lens: LensSpec) -> dict[str, str]:
    return {a.key: a.label for a in lens.attributes}


def _join(keys: set[str], labels: dict[str, str]) -> str:
    return ", ".join(sorted(labels.get(k, k) for k in keys))


def _detail(c: RunCandidate) -> dict[str, Any]:
    try:
        d = json.loads(c.excluded_detail or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def summarize_run(session: Session, run: VariationRun, lens: LensSpec) -> dict[str, Any]:
    """Counts by candidate state plus, when fewer than the result size came back, why."""
    cfg = RankingConfig.model_validate(run.ranking_config_json)
    labels = _labels(lens)
    target_label = labels.get(run.target_key, run.target_key)
    cands = runs_repo.candidates(session, run.id)
    extra_invalid = int((run.progress_json or {}).get("invalid_unindexed", 0))

    excluded: Counter[str] = Counter(c.excluded_reason or "unknown" for c in cands if
                                     c.state == "excluded")  # fmt: skip
    if extra_invalid:
        excluded["provenance"] += extra_invalid
    by_state = Counter(c.state for c in cands)
    returned = sum(1 for c in cands if c.rank is not None)
    out: dict[str, Any] = {
        "pool_size": len(cands),
        "excluded": dict(sorted(excluded.items())),
        "validated": by_state["validated"],
        "uncertain": by_state["uncertain"],
        "rejected": by_state["rejected"],
        "returned": returned,
    }
    if returned >= cfg.result_size:
        return out

    count: Counter[str] = Counter()
    attrs: dict[str, set[str]] = {k: set() for k in SHORTFALL_ORDER}
    for c in cands:
        if c.state == "excluded":
            d, r = _detail(c), c.excluded_reason
            if r == "hard_constraint":
                count["protected_changed"] += 1
                attrs["protected_changed"].add(str(d.get("attribute")))
            elif r == "no_target_change":
                count["no_target_change"] += 1
            elif r == "avoided_value":
                count["avoided_value"] += 1
            elif r == "on_board":
                count["on_board"] += 1
            elif r == "duplicate":
                count["duplicate_source" if d.get("duplicate_of") == "source" else
                      "duplicate_other"] += 1  # fmt: skip
            elif r == "provenance":
                count["provenance"] += 1
            elif r == "unusable":
                count["unusable"] += 1
        elif c.state in ("rejected", "uncertain"):
            checks = runs_repo.validations(session, c.id)
            if c.state == "uncertain":
                keys = {v.attribute_key for v in checks if v.verdict == "uncertain" and
                        v.attribute_key}  # fmt: skip
                count["uncertain"] += 1
                attrs["uncertain"] |= keys
                continue
            failed = {v.check: v for v in checks if v.verdict == "fail"}
            if "provenance" in failed:
                count["provenance"] += 1
            elif "duplicate" in failed:
                dup = (failed["duplicate"].evidence_json or {}).get("values", {})
                of_source = dup.get("duplicate_of") in (None, "source")
                count["duplicate_source" if of_source else "duplicate_other"] += 1
            elif "protected" in failed:
                count["protected_changed"] += 1
                attrs["protected_changed"].add(str(failed["protected"].attribute_key))
            else:
                count["target_not_met"] += 1
    if extra_invalid:
        count["provenance"] += extra_invalid
    if not cands and not extra_invalid:
        count["no_candidates"] = 1

    msgs = {
        "protected_changed": lambda n: (
            f"{n} changed a protected attribute ({_join(attrs['protected_changed'], labels)})"
        ),
        "target_not_met": lambda n: f"{n} did not deliver the {target_label} change you asked for",
        "uncertain": lambda n: (
            f"{n} had uncertain {_join(attrs['uncertain'], labels) or target_label}"
            " — under Needs review"
        ),
        "no_target_change": lambda n: f"{n} had the same {target_label} as your reference",
        "avoided_value": lambda n: f"{n} had a {target_label} you asked to avoid",
        "on_board": lambda n: f"{n} are already on your board",
        "duplicate_source": lambda n: f"{n} near-duplicates of your reference",
        "duplicate_other": lambda n: f"{n} near-duplicates of other results",
        "provenance": lambda n: f"{n} licensed images were excluded for invalid provenance",
        "unusable": lambda n: f"{n} images were unusable",
        "no_candidates": lambda n: "No licensed candidates were available for this board",
    }
    out["shortfall"] = [
        {"code": code, "count": count[code], "message": msgs[code](count[code])}
        for code in SHORTFALL_ORDER
        if count[code]
    ]
    return out
