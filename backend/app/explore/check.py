"""Check a generated item: ask directly whether it shows the option, compare the kept attributes.

The target is a direct visual question to the reasoning provider (re-parsing alone misses new
values). Kept attributes use the validator's comparators against the source; only keys whose
source value is reliable count, and an "unknown" verdict is neither kept nor drifted.
"""

import math
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Exploration, ExploreOption
from app.domain.attributes import AttributeRecord
from app.explore.prompts import build_check_prompt
from app.extraction.service import _image_for, _require_item, current_lens
from app.providers import get_reasoning
from app.retrieval.config import RANKING_CONFIG
from app.runs.orchestrator import source_records
from app.validation.comparators import AttrValue, compare

ANSWERS = ("yes", "no", "unclear")


def _confidence(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float) or math.isnan(raw):
        return None
    return min(1.0, max(0.0, float(raw)))


def _box(raw: Any) -> list[float] | None:
    """[x0, y0, x1, y1] in 0..1, else None."""
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
        return None
    if not all(0.0 <= v <= 1.0 for v in raw):  # NaN fails this too
        return None
    return [float(v) for v in raw]


def clean_target(raw: Any) -> dict[str, Any]:
    """The provider's answer reduced to {answer, confidence, box, note}; junk becomes unclear."""
    d = raw if isinstance(raw, dict) else {}
    answer = d.get("answer")
    answer = answer.strip().lower() if isinstance(answer, str) else ""
    note = d.get("note")
    return {
        "answer": answer if answer in ANSWERS else "unclear",
        "confidence": _confidence(d.get("confidence")),
        "box": _box(d.get("box")),
        "note": " ".join(note.split()) if isinstance(note, str) else "",
    }


def _missing() -> AttrValue:
    return AttrValue(None, 0.0, "missing")


def check_generated(
    session: Session, source_id: str, generated_id: str, option: ExploreOption
) -> dict[str, Any]:
    """{"target": {answer, confidence, box, note}, "kept": n, "of": m, "drifted": [keys]}."""
    e = session.get(Exploration, option.exploration_id)
    assert e is not None
    gen = _require_item(session, generated_id)
    lens = current_lens(session, gen.board_id)
    specs = {a.key: a for a in lens.attributes} if lens else {}
    target_spec = specs.get(e.key)
    prompt = build_check_prompt(
        label=target_spec.label if target_spec else e.key,
        option_name=option.name, description=option.description or "",
    )  # fmt: skip
    image, _sha = _image_for(session, gen)
    target = clean_target(get_reasoning(get_settings()).check_target([image], prompt))

    before: dict[str, AttributeRecord] = {r.key: r for r in source_records(session, source_id)}
    after: dict[str, AttributeRecord] = {r.key: r for r in source_records(session, generated_id)}
    kept, of, drifted = 0, 0, []
    for key in option.keeps_json or []:
        spec, src = specs.get(key), before.get(key)
        if spec is None or src is None:
            continue
        a = AttrValue.from_record(src)
        if not a.reliable(RANKING_CONFIG):
            continue
        b = AttrValue.from_record(after[key]) if key in after else _missing()
        of += 1
        verdict = compare(spec, a, b, RANKING_CONFIG)
        if verdict == "same":
            kept += 1
        elif verdict == "different":
            drifted.append(key)
    return {"target": target, "kept": kept, "of": of, "drifted": drifted}
