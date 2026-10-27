"""Per-kind validator: a candidate is validated only when every check passes with evidence.

Order: provenance, duplicate, then the target change and each protected attribute through the
comparators. Checks still uncertain (and every `text` check) go to one batched verify call per
<= 8 candidates, with source and candidate part crops. A segmentation mask never upgrades a
check: when SAM cannot find the part (in the candidate or the source) the check is judged by verify
on the whole images instead, and only a confident verify answer can pass it. Reasons are
deterministic templates; model text lives in `evidence`.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.config import get_settings
from app.corpus.hashing import hamming
from app.db.repos import corpus as corpus_repo
from app.db.repos import masks as masks_repo
from app.domain.kinds import AttributeSpec
from app.domain.lens import LensSpec, PartSpec
from app.domain.variation import VariationSpec
from app.extraction.schema import is_measured
from app.extraction.service import _part_mask, measure_attributes
from app.measure.crops import crop_part
from app.measure.palette import delta_e, to_rgb_array
from app.providers import get_reasoning, get_segmentation
from app.providers.reliability import ModelError
from app.retrieval.config import RankingConfig
from app.retrieval.filters import SourceItem, value_verdict
from app.retrieval.scores import Candidate, nudge_position
from app.storage import files
from app.validation import comparators
from app.validation.comparators import AttrValue, compare

VALIDATOR_VERSION = "val-3"

MAX_CANDIDATES_PER_CALL = 8
MAX_IMAGES_PER_CALL = 50
WHOLE_IMAGE_MAX_SIDE = 768

Verdict = Literal["pass", "fail", "uncertain"]
Overall = Literal["validated", "uncertain", "rejected"]

_PROVENANCE_REASONS = {
    "MISSING_SOURCE": "Source details are missing",
    "MISSING_CREATOR": "Creator credit is missing",
}

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate": {"type": "string"},
                    "key": {"type": "string"},
                    "answer": {
                        "type": "string",
                        "enum": ["same", "different", "cannot_tell", "more", "less"],
                    },
                    "steps": {"type": ["integer", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string"},
                },
                "required": ["candidate", "key", "answer", "steps", "confidence", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["checks"],
    "additionalProperties": False,
}


@dataclass
class CheckResult:
    check: Literal["target", "protected", "duplicate", "provenance"]
    verdict: Verdict
    reason: str
    evidence: dict[str, Any]
    attribute_key: str | None = None


@dataclass
class CandidateValidation:
    overall: Overall
    checks: list[CheckResult]
    observed_target_value: Any = None


@dataclass
class Providers:
    reasoning: Any = None
    segmentation: Any = None


# ---- wording ----


def _human(v: Any) -> str:
    if v is None:
        return "unknown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace("_", " ")


def _show(spec: AttributeSpec, v: AttrValue | None) -> str:
    if v is None or v.value is None:
        return "unknown"
    if spec.kind == "color":
        hexv = (v.measured or {}).get("hex")
        return str(hexv) if hexv else _human(v.value)
    if spec.kind == "number":
        return f"{_human(v.value)} {spec.unit}"  # type: ignore[union-attr]
    return _human(v.value)


def _part_label(part_id: str) -> str:
    return part_id.replace("_", " ").capitalize()


def _evidence_source(spec: AttributeSpec) -> str:
    if spec.kind in ("color", "shape"):
        return "measured"
    if spec.kind == "number" and spec.measure != "model":  # type: ignore[union-attr]
        return "measured"
    return "corpus_index"


# ---- mode conditions ----


def _apply_mode(mode: str, rels: Sequence[str]) -> Verdict:
    """The mode condition over same/different/unknown verdicts (shared by comparators and verify)."""
    if mode == "explore":
        return {"different": "pass", "same": "fail"}.get(rels[0], "uncertain")  # type: ignore[return-value]
    if mode == "protected":
        return {"same": "pass", "different": "fail"}.get(rels[0], "uncertain")  # type: ignore[return-value]
    if mode == "prefer":
        if "same" in rels:
            return "pass"
        return "fail" if all(r == "different" for r in rels) else "uncertain"
    if mode == "avoid":
        if "same" in rels:
            return "fail"
        return "pass" if all(r == "different" for r in rels) else "uncertain"
    return "uncertain"


def _relative(spec: AttributeSpec, cand: AttrValue, ref: AttrValue | None, fallback: Any,
              cfg: RankingConfig) -> str:  # fmt: skip
    if ref is not None and ref.value is not None:
        return compare(spec, cand, ref, cfg)
    return value_verdict(spec, cand, fallback, cfg)


# ---- check plan ----


@dataclass
class _Check:
    kind: Literal["target", "protected"]
    spec: AttributeSpec
    mode: str  # explore | prefer | avoid | nudge | protected
    src: AttrValue | None
    cand: AttrValue | None
    result: CheckResult
    ask: bool = False  # goes to the verify call
    crops: dict[str, bytes] = field(default_factory=dict)  # "source" / "candidate" -> PNG
    unfound: list[str] = field(default_factory=list)  # sides where SAM could not find the part

    @property
    def whole(self) -> bool:
        """Judged on the whole images (the part was not localised)."""
        return bool(self.unfound)

    def image_key(self) -> str:
        """The verify image a check reads: its part, or '' for the whole image."""
        return "" if self.whole else (self.spec.part or "")


def _unlocalised_note(c: _Check) -> str:
    return f"{_part_label(c.spec.part or '')} not localised; judged on the whole image"


def _localisation(c: _Check) -> dict[str, Any]:
    return {"part": c.spec.part, "not_found_in": list(c.unfound), "judged_on": "whole_image"}


def _unlocalise(c: _Check, side: str) -> None:
    """The part was not found on `side`: ask verify about the whole images; uncertain until then."""
    if side not in c.unfound:
        c.unfound.append(side)
    c.ask = True
    c.result = CheckResult(
        c.kind, "uncertain", f"{_unlocalised_note(c)}; the visual check could not tell",
        {"source": "segmentation", "values": {"part": c.spec.part},
         "localisation": _localisation(c)},
        c.spec.key,
    )  # fmt: skip


def _unknown_reason(spec: AttributeSpec, cand: AttrValue | None, mode: str) -> str:
    what = "kept" if mode == "protected" else "changed"
    if cand is None or cand.value is None:
        return f"{spec.label} could not be read, so it cannot be judged {what}"
    return f"{spec.label} is too uncertain to call"


def _relative_reason(spec: AttributeSpec, mode: str, rel: str, verdict: Verdict,
                     src: AttrValue | None, cand: AttrValue, cfg: RankingConfig) -> str:  # fmt: skip
    s, c = _show(spec, src), _show(spec, cand)
    word = "kept" if rel == "same" else "changed"
    if spec.kind == "color":
        sl = (src.measured or {}).get("lab") if src else None
        cl = (cand.measured or {}).get("lab")
        if sl is not None and cl is not None:
            de = delta_e(tuple(sl), tuple(cl))  # type: ignore[arg-type]
            if rel == "unknown":
                return f"{spec.label} {s} → {c} (ΔE {de:.0f}) — too close to call"
            return (
                f"{spec.label} kept: {s} (ΔE {de:.0f})"
                if rel == "same"
                else f"{spec.label} changed: {s} → {c} (ΔE {de:.0f})"
            )
    if spec.kind == "shape":
        sim = comparators.shape_similarity(src.measured, cand.measured)  # type: ignore[arg-type,union-attr]
        if rel == "unknown":
            return f"{spec.label} similarity {sim:.2f} — too close to call"
        return f"{spec.label} {word} (similarity {sim:.2f})"
    if rel == "unknown":
        return _unknown_reason(spec, cand, mode)
    if spec.kind == "text":
        return f"{spec.label} {word}"
    if rel == "same":
        return f"{spec.label} kept: {c}"
    return f"{spec.label} changed: {s} → {c}"


def _values_reason(spec: AttributeSpec, mode: str, verdict: Verdict, cand: AttrValue,
                   values: tuple[Any, ...]) -> str:  # fmt: skip
    listed = ", ".join(_human(v) for v in values)
    c = _show(spec, cand)
    if verdict == "uncertain":
        return f"{spec.label} {c} is too close to call against {listed}"
    if mode == "prefer":
        return (
            f"{spec.label} is {c}, a preferred value"
            if verdict == "pass"
            else (f"{spec.label} is {c}, not one of the preferred values ({listed})")
        )
    return (
        f"{spec.label} is {c}, not an avoided value"
        if verdict == "pass"
        else (f"{spec.label} {c} is an avoided value")
    )


def _steps_word(n: int) -> str:
    return f"{n} step" if n == 1 else f"{n} steps"


def _nudge_label(spec: VariationSpec) -> str:
    n = spec.request.nudge
    assert n is not None
    return f"{spec.target_spec.label} {'+' if n.direction == 'more' else '-'}{_steps_word(n.steps)}"


def _evaluate(spec: AttributeSpec, mode: str, vspec: VariationSpec | None, src: AttrValue | None,
              cand: AttrValue | None, fallback: Any, cfg: RankingConfig
              ) -> tuple[Verdict, str, dict[str, Any]]:  # fmt: skip
    ev: dict[str, Any] = {"source": _evidence_source(spec)}
    if cand is None or cand.value is None:
        return "uncertain", _unknown_reason(spec, cand, mode), ev
    ev["values"] = {"candidate": cand.value, "source": src.value if src else fallback}
    if mode == "nudge":
        assert vspec is not None
        pos = nudge_position(vspec, cand, cfg)
        head = _nudge_label(vspec)
        if pos is None:
            return "uncertain", f"{head}: {_show(spec, cand)} cannot be placed reliably", ev
        shown = f"{_show(spec, src) if src else _human(fallback)} → {_show(spec, cand)}"
        if pos == "exact":
            return "pass", f"{head}: {shown}", ev
        if pos == "near":
            return "uncertain", f"{head}: {shown} is too close to call", ev
        return "fail", f"{head} not met: {shown}", ev
    if mode in ("prefer", "avoid"):
        assert vspec is not None
        rels = [value_verdict(spec, cand, v, cfg) for v in vspec.values]
        verdict = _apply_mode(mode, rels)
        return verdict, _values_reason(spec, mode, verdict, cand, vspec.values), ev
    rel = _relative(spec, cand, src, fallback, cfg)
    verdict = _apply_mode(mode, [rel])
    ref = src if src is not None and src.value is not None else None
    if spec.kind == "color" and ref is not None:
        sl, cl = (ref.measured or {}).get("lab"), (cand.measured or {}).get("lab")
        if sl is not None and cl is not None:
            ev["values"]["delta_e"] = round(delta_e(tuple(sl), tuple(cl)), 1)  # type: ignore[arg-type]
    if (
        spec.kind == "shape"
        and ref
        and ref.measured
        and cand.measured
        and ("hu" in ref.measured and "hu" in cand.measured)
    ):
        sim = comparators.shape_similarity(ref.measured, cand.measured)
        ev["values"]["similarity"] = round(sim, 2)
    if spec.kind in ("color", "shape") and ref is None and rel == "unknown":
        reason = _unknown_reason(spec, cand, mode)
    else:
        reason = _relative_reason(spec, mode, rel, verdict, ref or AttrValue(fallback, 1.0, "x"),
                                  cand, cfg)  # fmt: skip
    return verdict, reason, ev


# ---- images ----


class _Images:
    """Decoded originals, masks and crops for one validate call."""

    def __init__(self, session: Session, providers: Providers, lens: LensSpec) -> None:
        self.session, self.providers, self.lens = session, providers, lens
        self._rgb: dict[str, np.ndarray | None] = {}
        self._crops: dict[tuple[str, str], tuple[bytes | None, str]] = {}
        self._seg: Any = None

    def seg(self) -> Any:
        if self._seg is None:
            self._seg = self.providers.segmentation or get_segmentation(get_settings())
        return self._seg

    def rgb(self, path: str | None) -> np.ndarray | None:
        if not path:
            return None
        if path not in self._rgb:
            p = files.abs_path(path)
            try:
                self._rgb[path] = to_rgb_array(p.read_bytes()) if p.is_file() else None
            except (OSError, ValueError):
                self._rgb[path] = None
        return self._rgb[path]

    def whole(self, rgb: np.ndarray) -> bytes:
        im = Image.fromarray(rgb, "RGB")
        im.thumbnail((WHOLE_IMAGE_MAX_SIDE, WHOLE_IMAGE_MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    def part(self, part_id: str | None) -> PartSpec | None:
        return next((p for p in self.lens.parts if p.id == part_id), None)

    def crop(self, path: str | None, sha: str | None, part_id: str | None
             ) -> tuple[bytes | None, str]:  # fmt: skip
        """(PNG, status): status is ok | not_visible | unavailable:<CODE>."""
        key = (path or "", part_id or "")
        if key in self._crops:
            return self._crops[key]
        out = self._crop(path, sha, part_id)
        self._crops[key] = out
        return out

    def _crop(self, path: str | None, sha: str | None, part_id: str | None
              ) -> tuple[bytes | None, str]:  # fmt: skip
        rgb = self.rgb(path)
        if rgb is None:
            return None, "unavailable:IMAGE_MISSING"
        part = self.part(part_id)
        if part is None or part.grounding == "whole_image":
            return self.whole(rgb), "ok"
        sha = sha or files.sha256_hex(files.abs_path(path or "").read_bytes())
        try:
            row = masks_repo.get(self.session, sha, part.sam_prompt)
            mask = None
            if row is None or row.found:
                h, w = rgb.shape[:2]
                mask, _ = _part_mask(
                    self.session, _LazySeg(self), files.abs_path(path or "").read_bytes(), sha,
                    part.sam_prompt, (h, w),
                )  # fmt: skip
            row = masks_repo.get(self.session, sha, part.sam_prompt)
        except ModelError as e:
            return None, f"unavailable:{e.code}"
        if row is not None and not row.found:
            return None, "not_visible"
        if mask is None or not mask.any():
            return None, "unavailable:MASK_MISSING"
        return crop_part(rgb, mask), "ok"


class _LazySeg:
    """Resolves the segmentation provider only if a mask is actually missing from the cache."""

    def __init__(self, images: _Images) -> None:
        self._images = images

    @property
    def id(self) -> str:
        return str(self._images.seg().id)

    def localize(self, image: bytes, sha: str, noun: str) -> Any:
        return self._images.seg().localize(image, sha, noun)


# ---- quick-indexed (live) candidates ----


def _measure_quick(
    session: Session, images: _Images, c: Candidate, specs: Sequence[AttributeSpec], lens: LensSpec
) -> None:  # fmt: skip
    """Fill only the measurable attributes this run checks on a quick-indexed item.

    SAM runs for the parts of those attributes alone (masks are cached); colour, number and shape
    are measured in code and stored. Everything else (enum, ordinal, boolean, text) stays unknown
    here and is resolved by the verify call, which compares against the source image.
    """
    item = c.pool.item
    if getattr(item, "index_depth", None) != "quick" or not item.local_path or not item.sha256:
        return
    todo = [s for s in specs if s.key not in c.pool.attrs and is_measured(s)]
    if not todo:
        return
    rgb = images.rgb(item.local_path)
    if rgb is None:
        return
    data = files.abs_path(item.local_path).read_bytes()
    grounded: dict[str, Any] = {}
    usable: list[AttributeSpec] = []
    for spec in todo:
        part = images.part(spec.part)
        if part is not None and part.grounding == "sam":
            if part.id not in grounded:
                try:
                    grounded[part.id] = _part_mask(
                        session, _LazySeg(images), data, item.sha256, part.sam_prompt, rgb.shape[:2]
                    )  # fmt: skip
                except ModelError:
                    continue  # unknown stays unknown; verify reports the failure
            if grounded[part.id][0] is None:
                continue  # the part is not visible: never measure the wrong region
        usable.append(spec)
    if not usable:
        return
    for rec in measure_attributes(lens.model_copy(update={"attributes": usable}), rgb, grounded):
        if rec.value is None:
            continue
        row = corpus_repo.set_attribute(
            session, item.id, rec.key, value_json=rec.value, confidence=rec.confidence,
            source=rec.source, evidence_json=rec.evidence.model_dump(mode="json"),
            measured_json=rec.measured,
        )  # fmt: skip
        c.pool.attrs[rec.key] = AttrValue.from_row(row)
    session.commit()  # short write: nothing stays pending across the next SAM or verify call


# ---- verify ----


def _question(c: _Check, vspec: VariationSpec, src_i: int | None, cand_i: int) -> str:
    spec = c.spec
    label = spec.label
    if c.mode in ("prefer", "avoid"):
        listed = ", ".join(_human(v) for v in vspec.values)
        return (
            f"Does the candidate (image {cand_i}) show a {label} matching any of: {listed}? "
            "Answer same for yes, different for no, or cannot_tell."
        )
    ref = f"the source (image {src_i})" if src_i is not None else "the source"
    if c.mode == "nudge":
        n = vspec.request.nudge
        assert n is not None
        scale = (
            f" Scale from low to high: {', '.join(_human(s) for s in spec.scale)}."  # type: ignore[union-attr]
            if spec.kind == "ordinal" else ""
        )  # fmt: skip
        return (
            f"Compared with {ref}, does the candidate (image {cand_i}) have more or less {label}? "
            f"Answer more, less or same, with the number of steps.{scale} "
            "Answer cannot_tell if unsure."
        )
    return (
        f"Is the {label} of the candidate (image {cand_i}) the same as in {ref}? "
        "Answer same, different or cannot_tell."
    )


def _answer_verdict(c: _Check, vspec: VariationSpec, answer: str, steps: Any) -> Verdict | None:
    if c.mode == "nudge":
        n = vspec.request.nudge
        assert n is not None
        if answer == "same":
            return "fail"
        if answer in ("more", "less"):
            if not isinstance(steps, int) or isinstance(steps, bool):
                return None
            return "pass" if answer == n.direction and steps == n.steps else "fail"
        return None
    if answer in ("same",):
        rel = "same"
    elif answer in ("different", "more", "less"):
        rel = "different"
    else:
        return None
    return _apply_mode(c.mode, [rel])


def _verify_reason(c: _Check, vspec: VariationSpec, verdict: Verdict) -> str:
    label = c.spec.label
    if c.mode == "nudge":
        head = _nudge_label(vspec)
        return f"{head} {'confirmed' if verdict == 'pass' else 'not met'} by visual check"
    if c.mode == "protected":
        word = "kept" if verdict == "pass" else "changed"
    elif c.mode == "explore":
        word = "changed" if verdict == "pass" else "kept"
    elif c.mode == "prefer":
        return f"{label} {'matches' if verdict == 'pass' else 'does not match'} a preferred value (visual check)"
    else:
        return f"{label} {'avoids' if verdict == 'pass' else 'matches'} the avoided values (visual check)"
    return f"{label} {word} (visual check)"


def _verify_batch(
    reasoning: Any, images: _Images, vspec: VariationSpec, src: SourceItem,
    batch: list[tuple[str, list[_Check]]], cfg: RankingConfig,
) -> None:  # fmt: skip
    """One verify call for these candidates; resolves their `ask` checks in place."""
    pngs: list[bytes] = []
    notes: list[str] = []
    src_index: dict[str, int] = {}
    questions: list[str] = []
    asked: dict[tuple[str, str], _Check] = {}

    def add(png: bytes, note: str) -> int:
        pngs.append(png)
        notes.append(f"Image {len(pngs) - 1}: {note}")
        return len(pngs) - 1

    for cid, checks in batch:
        for c in checks:
            if c.mode in ("prefer", "avoid") or "source" not in c.crops:
                continue
            part = c.image_key()
            if part not in src_index:
                src_index[part] = add(c.crops["source"], f"source, {_part_text(part)}")
    for cid, checks in batch:
        cand_index: dict[str, int] = {}
        for c in checks:
            part = c.image_key()
            if part not in cand_index:
                cand_index[part] = add(c.crops["candidate"], f"candidate {cid}, {_part_text(part)}")
            si = None if c.mode in ("prefer", "avoid") else src_index.get(part)
            questions.append(f"[{cid} / {c.spec.key}] {_question(c, vspec, si, cand_index[part])}")
            asked[(cid, c.spec.key)] = c
    prompt = (
        "You verify whether candidate images keep or change attributes of a source image. "
        "Answer each question below with the candidate id and attribute key shown in brackets, "
        "an answer, steps (an integer for more/less answers, otherwise null), a confidence "
        "from 0 to 1 and one sentence of evidence.\n\n"
        + "\n".join(notes) + "\n\nQuestions:\n" + "\n".join(questions)
    )  # fmt: skip
    try:
        out = reasoning.verify(pngs, VERIFY_SCHEMA, prompt)
    except ModelError as e:
        for c in asked.values():
            _unavailable(c, e.code)
        return
    rows = out.get("checks") if isinstance(out, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        found = asked.get((str(row.get("candidate")), str(row.get("key"))))
        if found is None:
            continue
        c = found
        try:
            conf = float(row.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if conf < cfg.reliable_confidence:
            continue
        verdict = _answer_verdict(c, vspec, str(row.get("answer")), row.get("steps"))
        if verdict is None:
            continue
        ev: dict[str, Any] = {
            "source": "verify", "confidence": conf,
            "values": {"answer": row.get("answer"), "steps": row.get("steps"),
                       "note": str(row.get("evidence", ""))},
        }  # fmt: skip
        reason = _verify_reason(c, vspec, verdict)
        if c.whole:
            reason = f"{reason}. {_unlocalised_note(c)}"
            ev["localisation"] = _localisation(c)
        c.result = CheckResult(c.kind, verdict, reason, ev, c.spec.key)
        c.ask = False


def _unavailable(c: _Check, code: str) -> None:
    reason = f"verification unavailable ({code})"
    ev: dict[str, Any] = {"source": "verify", "values": {"error": code}}
    if c.whole:
        reason = f"{_unlocalised_note(c)}; {reason}"
        ev["localisation"] = _localisation(c)
    c.result = CheckResult(c.kind, "uncertain", reason, ev, c.spec.key)
    c.ask = False


def _part_text(part: str) -> str:
    return _part_label(part) if part else "whole image"


def _batches(
    work: list[tuple[str, list[_Check]]], vspec: VariationSpec
) -> list[list[tuple[str, list[_Check]]]]:
    """<= 8 candidates and <= 50 images per call."""
    out: list[list[tuple[str, list[_Check]]]] = []
    cur: list[tuple[str, list[_Check]]] = []
    used = 0

    def cost(cid: str, checks: list[_Check]) -> tuple[int, set[str]]:
        return len({c.image_key() for c in checks}), {
            c.image_key() for c in checks if c.mode not in ("prefer", "avoid")
        }

    src_parts: set[str] = set()
    for cid, checks in work:
        n, sp = cost(cid, checks)
        extra = n + len(sp - src_parts)
        if cur and (len(cur) >= MAX_CANDIDATES_PER_CALL or used + extra > MAX_IMAGES_PER_CALL):
            out.append(cur)
            cur, used, src_parts = [], 0, set()
            extra = n + len(sp)
        cur.append((cid, checks))
        used += extra
        src_parts |= sp
    if cur:
        out.append(cur)
    return out


# ---- main ----


def _provenance(c: Candidate) -> CheckResult:
    item = c.pool.item
    ev = {"source": "corpus_index"}
    if item.provenance_status == "invalid":
        issue = item.provenance_issue
        if issue == "LICENSE_NOT_ALLOWED":
            reason = f"Licence {item.license_code} is not allowed"
        else:
            reason = _PROVENANCE_REASONS.get(issue or "", "Provenance is invalid")
        return CheckResult("provenance", "fail", reason, {**ev, "values": {"issue": issue}})
    return CheckResult("provenance", "pass", f"Licence {item.license_code} is allowed", ev)


def _duplicate(c: Candidate, src: SourceItem, kept: list[Candidate], cfg: RankingConfig
               ) -> CheckResult:  # fmt: skip
    item = c.pool.item
    ev = {"source": "corpus_index"}
    if (src.sha256 and item.sha256 == src.sha256) or (
        src.corpus_item_id and item.id == src.corpus_item_id
    ):
        return CheckResult("duplicate", "fail", "Same image as the source",
                           {**ev, "values": {"duplicate_of": "source"}})  # fmt: skip
    if item.dhash:
        if src.dhash and hamming(item.dhash, src.dhash) <= cfg.duplicate_dhash_distance:
            return CheckResult("duplicate", "fail", "Near-duplicate of the source",
                               {**ev, "values": {"duplicate_of": "source"}})  # fmt: skip
        for k in kept:
            kd = k.pool.item.dhash
            if kd and hamming(item.dhash, kd) <= cfg.duplicate_dhash_distance:
                return CheckResult("duplicate", "fail", "Near-duplicate of another result",
                                   {**ev, "values": {"duplicate_of": k.pool.item.id}})  # fmt: skip
    return CheckResult("duplicate", "pass", "Not a duplicate", ev)


def _overall(checks: list[CheckResult]) -> Overall:
    if any(c.verdict == "fail" for c in checks):
        return "rejected"
    if any(c.verdict == "uncertain" for c in checks):
        return "uncertain"
    return "validated"


def validate_shortlist(
    session: Session,
    spec: VariationSpec,
    source_item: SourceItem,
    cands: list[Candidate],
    lens: LensSpec,
    cfg: RankingConfig,
    providers: Providers | None = None,
) -> dict[str, CandidateValidation]:
    providers = providers or Providers()
    images = _Images(session, providers, lens)
    tspec, mode = spec.target_spec, spec.request.mode

    results: dict[str, list[CheckResult]] = {}
    plans: dict[str, list[_Check]] = {}
    observed: dict[str, Any] = {}
    kept: list[Candidate] = []

    for c in cands:
        cid = c.pool.item.id
        checks = [_provenance(c)]
        checks.append(_duplicate(c, source_item, kept, cfg))
        results[cid] = checks
        observed[cid] = (c.pool.attrs.get(tspec.key) or AttrValue(None, 0, "missing")).value
        if any(x.verdict == "fail" for x in checks):
            continue
        kept.append(c)
        plan: list[_Check] = []
        specs: list[tuple[Literal["target", "protected"], AttributeSpec, str, Any]] = [
            ("target", tspec, mode, spec.target_value)
        ]
        specs += [("protected", p.spec, "protected", p.value) for p in spec.protected]
        _measure_quick(session, images, c, [t[1] for t in specs], lens)
        observed[cid] = (c.pool.attrs.get(tspec.key) or AttrValue(None, 0, "missing")).value
        for kind, aspec, amode, fallback in specs:
            cand_attr = c.pool.attrs.get(aspec.key)
            src_attr = source_item.attrs.get(aspec.key)
            verdict, reason, ev = _evaluate(
                aspec, amode, spec, src_attr, cand_attr, fallback, cfg
            )  # fmt: skip
            check = _Check(kind, aspec, amode, src_attr, cand_attr,
                           CheckResult(kind, verdict, reason, ev, aspec.key))  # fmt: skip
            check.ask = verdict == "uncertain" or aspec.kind == "text"
            plan.append(check)
        # segmentation: a part SAM cannot find is judged on the whole image; a mask never upgrades
        for ck in plan:
            part_id = ck.spec.part
            part = images.part(part_id)
            if part is None or part.grounding == "whole_image":
                continue
            png, status = images.crop(
                c.pool.item.local_path, c.pool.item.sha256, part_id
            )  # fmt: skip
            if status == "not_visible":
                _unlocalise(ck, "candidate")
            elif png is None:
                code = status.split(":", 1)[1]
                ck.result = CheckResult(
                    ck.kind, "uncertain", f"verification unavailable ({code})",
                    {"source": "segmentation", "values": {"error": code}}, ck.spec.key,
                )  # fmt: skip
                ck.ask = False
        plans[cid] = plan

    # crops for the checks that go to verify
    work: list[tuple[str, list[_Check]]] = []
    for c in kept:
        cid = c.pool.item.id
        asking = [ck for ck in plans[cid] if ck.ask]
        ready: list[_Check] = []
        for ck in asking:
            part_id = None if ck.whole else ck.spec.part
            png, status = images.crop(c.pool.item.local_path, c.pool.item.sha256, part_id)
            if png is None:
                ck.result = CheckResult(
                    ck.kind, "uncertain", f"verification unavailable ({status.split(':')[-1]})",
                    {"source": "verify", "values": {"error": status}}, ck.spec.key,
                )  # fmt: skip
                ck.ask = False
                continue
            ck.crops["candidate"] = png
            if ck.mode not in ("prefer", "avoid"):
                spng, sstatus = images.crop(source_item.storage_path, source_item.sha256, part_id)
                if spng is None and sstatus == "not_visible":
                    # not found in the source: both sides are judged on the whole image
                    _unlocalise(ck, "source")
                    cpng, _ = images.crop(c.pool.item.local_path, c.pool.item.sha256, None)
                    spng, sstatus = images.crop(source_item.storage_path, source_item.sha256, None)
                    if cpng is not None:
                        ck.crops["candidate"] = cpng
                if spng is None:
                    ck.result = CheckResult(
                        ck.kind, "uncertain",
                        f"verification unavailable ({sstatus.split(':')[-1].upper()})",
                        {"source": "verify", "values": {"error": sstatus}}, ck.spec.key,
                    )  # fmt: skip
                    ck.ask = False
                    continue
                ck.crops["source"] = spng
            ready.append(ck)
        if ready:
            work.append((cid, ready))

    if work:
        try:
            reasoning = providers.reasoning or get_reasoning(get_settings())
        except ModelError as e:
            reasoning = None
            for _, cks in work:
                for ck in cks:
                    _unavailable(ck, e.code)
        if reasoning is not None:
            for batch in _batches(work, spec):
                _verify_batch(reasoning, images, spec, source_item, batch, cfg)

    out: dict[str, CandidateValidation] = {}
    for c in cands:
        cid = c.pool.item.id
        checks = results[cid] + [ck.result for ck in plans.get(cid, [])]
        out[cid] = CandidateValidation(_overall(checks), checks, observed[cid])
    return out
