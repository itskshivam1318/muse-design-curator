"""Check a generated item: ask directly whether it shows the option, compare the held dimensions.

The target is a direct visual question to the reasoning provider (re-parsing alone misses new
values). Every other dimension of the source item still found on it (not removed, not stale)
is held, whatever the option's keeps say: each whose source value is reliable is compared
with the validator's comparators; `of` counts the decidable ones (kept + drifted) and the ones
the comparator calls "unknown" (a key the take does not carry among them) are counted apart."""

import math
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.spec import spec_for
from app.config import get_settings
from app.db.models import Exploration, ExploreOption, ItemAttribute
from app.domain.lens import LensSpec
from app.explore.prompts import build_check_prompt
from app.explore.service import dimensions, is_held
from app.extraction.service import _image_for, _require_item, current_lens
from app.providers import get_reasoning
from app.retrieval.config import RANKING_CONFIG
from app.runs.orchestrator import record_of
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


def _label(row: ItemAttribute | None, key: str, lens: LensSpec | None) -> str:
    """The explored dimension's label: the item's own, else the lens's, else its key."""
    if row is not None:
        return spec_for(row, lens).label
    return next((a.label for a in lens.attributes if a.key == key), key) if lens else key


def check_generated(
    session: Session, source_id: str, generated_id: str, option: ExploreOption
) -> dict[str, Any]:
    """{"target": {answer, confidence, box, note}, "kept": n, "of": m, "drifted": [keys],
    "unknown": k}: `of` is the decidable held dimensions (kept + drifted), `unknown` the ones
    the comparator could not judge."""
    e = session.get(Exploration, option.exploration_id)
    assert e is not None
    gen = _require_item(session, generated_id)
    lens = current_lens(session, gen.board_id)
    rows = dimensions(session, source_id)
    target = next((r for r in rows if r.key == e.key), None)
    specs = {r.key: spec_for(r, lens) for r in rows}
    prompt = build_check_prompt(
        label=_label(target, e.key, lens),
        option_name=option.name, description=option.description or "",
    )  # fmt: skip
    images: list[bytes]
    if gen.kind == "note":  # a rewritten passage: the question is put to its text
        images = []
        text = gen.note_text or ""
        prompt += f"\n\nThere is no image: the item is this text.\n<<<TEXT\n{text}\nTEXT>>>"
    else:
        images = [_image_for(session, gen)[0]]
    answer = clean_target(get_reasoning(get_settings()).check_target(images, prompt))

    before = {r.key: record_of(r) for r in rows if is_held(r)}
    after = {r.key: record_of(r) for r in dimensions(session, generated_id) if is_held(r)}
    kept, unknown, drifted = 0, 0, []
    for key, src in before.items():
        if key == e.key:
            continue
        a = AttrValue.from_record(src)
        if not a.reliable(RANKING_CONFIG):
            continue
        b = AttrValue.from_record(after[key]) if key in after else _missing()
        verdict = compare(specs[key], a, b, RANKING_CONFIG)
        if verdict == "same":
            kept += 1
        elif verdict == "different":
            drifted.append(key)
        else:
            unknown += 1
    return {
        "target": answer, "kept": kept, "of": kept + len(drifted), "drifted": drifted,
        "unknown": unknown,
    }  # fmt: skip


def check_target_only(image: bytes, note_text: str) -> dict[str, Any]:
    """Ask the direct target question of a generated image against a note's text:
    {"target_ok": True/False, or None when the answer is unclear, "answer": yes/no/unclear}."""
    prompt = build_check_prompt(label="subject", option_name=note_text, description="")
    target = clean_target(get_reasoning(get_settings()).check_target([image], prompt))
    answer = target["answer"]
    return {"target_ok": {"yes": True, "no": False}.get(answer), "answer": answer}
