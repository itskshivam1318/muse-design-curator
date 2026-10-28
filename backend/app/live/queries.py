"""Live search queries: one small reasoning call turns the variation into 3-5 short searches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.domain.lens import LensSpec
from app.domain.variation import VariationSpec
from app.providers.cache import cached_call
from app.validation.comparators import AttrValue

PROMPT_VERSION = "live-queries-v2"
MIN_QUERIES, MAX_QUERIES = 3, 5

QUERIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": MIN_QUERIES,
            "maxItems": MAX_QUERIES,
        }
    },
    "required": ["queries"],
    "additionalProperties": False,
}


class QueriesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str]

    @field_validator("queries")
    @classmethod
    def _shape(cls, v: list[str]) -> list[str]:
        out = [q.strip() for q in v]
        if not MIN_QUERIES <= len(out) <= MAX_QUERIES or not all(out):
            raise ValueError(f"expected {MIN_QUERIES}-{MAX_QUERIES} non-empty queries")
        return out


def _human(v: Any) -> str:
    return "unknown" if v is None else str(v).replace("_", " ")


def _protected_text(spec: VariationSpec, source_attrs: dict[str, AttrValue]) -> list[str]:
    out = []
    for p in spec.protected:
        src = source_attrs.get(p.key)
        value = src.value if src is not None and src.value is not None else p.value
        out.append(f"{p.spec.label}: {_human(value)}")
    return out


def _target_text(spec: VariationSpec) -> str:
    label, mode = spec.target_spec.label, spec.request.mode
    values = ", ".join(_human(v) for v in spec.values)
    if mode == "prefer":
        return f"change the {label} to one of: {values}"
    if mode == "avoid":
        return f"change the {label} to anything except: {values}"
    if mode == "nudge" and spec.request.nudge:
        n = spec.request.nudge
        return f"{n.direction} {label} by {n.steps} step(s)"
    return f"a different {label} (the reference has {_human(spec.target_value)})"


def build_prompt(
    spec: VariationSpec, source_attrs: dict[str, AttrValue], lens: LensSpec, board_context: str
) -> str:
    protected = _protected_text(spec, source_attrs)
    lines = [
        (
            f"Write {MIN_QUERIES} to {MAX_QUERIES} short image-search queries (2 to 4 words "
            "each) for openly licensed image archives (Wikimedia Commons, Openverse, museums)."
        ),
        f"The reference is a '{lens.label}' image. We want images with: {_target_text(spec)}.",
    ]
    if protected:
        lines.append(
            "These must stay as in the reference: " + "; ".join(protected) + ". "
            "Name one or two of them in each query."
        )
    if board_context.strip():
        lines.append(f"Board context: {board_context.strip()}")
    lines.append(
        "Each query names the target change plus at most one protected cue. "
        "These archives match words in photo titles and captions, so use everyday words a "
        "photographer would write, not specialist jargon. "
        "Plain words only: no quotes, no operators, no site names."
    )
    return "\n".join(lines)


def fallback_queries(spec: VariationSpec, lens: LensSpec) -> list[str]:
    """Deterministic queries from the lens labels, used when the model cannot answer."""
    noun = lens.label.lower()
    target = spec.target_spec.label.lower()
    words = [_human(v) for v in spec.values] or [target]
    prot = [p.spec.label.lower() for p in spec.protected][:2]
    out = [f"{noun} {w}".strip() for w in words[:2]]
    out.append(f"{noun} {target}")
    out.append(" ".join([noun, *prot]).strip())
    seen: list[str] = []
    for q in out:
        if q and q not in seen:
            seen.append(q)
    extra = f"{noun} collection"
    while len(seen) < MIN_QUERIES:
        seen.append(extra if extra not in seen else f"{extra} photo")
    return seen[:MAX_QUERIES]


def broad_queries(spec: VariationSpec, lens: LensSpec) -> list[str]:
    """Two plain 2-3 word searches that keyword archives reliably answer.

    Model-written queries can be too specific for a title/caption search and return nothing;
    these keep the live pool from coming back empty.
    """
    noun = lens.label.lower()
    t = spec.target_spec
    part = next((p.sam_prompt for p in lens.parts if p.id == t.part), None) if t.part else None
    first = _human(spec.values[0]) if spec.request.mode == "prefer" and spec.values else None
    out = [part or noun, f"{noun} {first or t.label.lower()}"]
    return list(dict.fromkeys(q.strip() for q in out if q.strip()))


def with_broad(queries: list[str], spec: VariationSpec, lens: LensSpec) -> list[str]:
    """The given queries, then the broad ones not already among them (case-insensitive)."""
    seen = {q.lower() for q in queries}
    return queries + [q for q in broad_queries(spec, lens) if q.lower() not in seen]


def write_queries(
    spec: VariationSpec,
    source_attrs: dict[str, AttrValue],
    lens: LensSpec,
    board_context: str,
    provider: Any,
    *,
    session: Session,
    timeout: float | None = None,
) -> list[str]:
    """3-5 queries from one `provider.extract` call, cached by prompt and provider."""
    prompt = build_prompt(spec, source_attrs, lens, board_context)
    key_parts = [provider.id, provider.model, PROMPT_VERSION, prompt]

    def call() -> Any:
        if timeout is None:
            return provider.extract([], QUERIES_SCHEMA, prompt)
        # the session stays on this thread; only the provider call is bounded
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-q")
        try:
            return ex.submit(provider.extract, [], QUERIES_SCHEMA, prompt).result(timeout=timeout)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    raw = cached_call(session, key_parts, None, call)
    if isinstance(raw, dict) and isinstance(raw.get("queries"), list):
        qs = [q for q in raw["queries"] if isinstance(q, str)]
        if len(qs) > MAX_QUERIES:  # a model that over-delivers is trimmed, not rejected
            raw = {**raw, "queries": raw["queries"][:MAX_QUERIES]}
    return QueriesOut.model_validate(raw).queries
