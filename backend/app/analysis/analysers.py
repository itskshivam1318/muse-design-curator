"""One reasoning call per item: classify it, name its parts, and read its dimensions.

The answer is validated element by element so one malformed part or dimension is dropped
instead of failing the whole analysis.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analysis.types import (
    ANALYSIS_SCHEMA,
    MAX_DIMENSIONS,
    MAX_PARTS,
    Analysis,
    DimensionOut,
    PartOut,
    Region,
)
from app.config import get_settings
from app.db.models import BoardItem
from app.domain.attributes import canonical_token
from app.errors import AppError
from app.extraction.service import _image_for
from app.providers import get_reasoning

log = logging.getLogger(__name__)

TEXT_OPEN = "<<<TEXT"
TEXT_CLOSE = "TEXT>>>"


@dataclass
class ItemContent:
    item_id: str
    kind: str
    image: bytes | None = None
    text: str | None = None


@dataclass
class Hints:
    board_dimensions: list[dict[str, Any]] = field(default_factory=list)
    abstract_definitions: list[dict[str, Any]] = field(default_factory=list)
    you_parts: list[str] = field(default_factory=list)
    you_dimensions: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    parent_dimensions: list[dict[str, Any]] = field(default_factory=list)
    content_type: str | None = None  # set when the person chose what the item is

    @classmethod
    def empty(cls) -> "Hints":
        return cls()


def load_content(session: Session, item: BoardItem) -> ItemContent:
    if item.kind in ("image", "video"):
        image, _sha = _image_for(session, item)
        return ItemContent(item_id=item.id, kind=item.kind, image=image)
    if item.kind == "note" and item.note_text and item.note_text.strip():
        return ItemContent(item_id=item.id, kind="note", text=item.note_text)
    raise AppError(400, "UNSUPPORTED_ITEM", "This item cannot be analysed")


def _labels(rows: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{r.get('label', '')}" + (f" ({r['prompt']})" if r.get("prompt") else "") for r in rows
    )


def build_prompt(content: ItemContent, board_context: str, hints: Hints) -> str:
    is_text = content.text is not None
    lines = [
        "Analyse this item for a design board. Answer with JSON matching the schema.",
        "1. Classify content_type: "
        + (
            "'text' (this item is a written note)."
            if is_text
            else "'ui' if it is a screenshot of software, otherwise 'image'."
        ),
        f"2. Name up to {MAX_PARTS} distinct parts of the item (snake_case keys, short labels). "
        + (
            "Each text part is a 'text_range' region: [start, end] character offsets into the text."
            if is_text
            else "Parts of a UI screenshot use region_kind 'box' with [x0, y0, x1, y1] in 0..1; "
            "parts of an image use region_kind 'mask' with region null."
        ),
        (
            "3. For each part give its physical dimensions (type 'physical', part = the part "
            "key): concrete, observable attributes such as colour, material, shape or size."
        ),
        (
            "4. Give 2 to 6 abstract dimensions about the whole item (type 'abstract', part "
            "null), each with a one-sentence `prompt` that asks the question it answers."
        ),
        (
            f"At most {MAX_DIMENSIONS} dimensions in total. Each needs a snake_case key, "
            "a kind, a value and a confidence in 0..1."
        ),
    ]
    if hints.content_type and not is_text:
        lines.append(f"The user has set content_type to '{hints.content_type}'; use exactly that.")
    if hints.abstract_definitions:
        lines.append(
            "Reuse these abstract dimension labels and prompts exactly when they apply: "
            + _labels(hints.abstract_definitions)
        )
    if hints.board_dimensions:
        lines.append(
            "Dimensions already used on this board; reuse their labels when they apply: "
            + _labels(hints.board_dimensions)
        )
    if hints.you_parts or hints.you_dimensions:
        lines.append(
            "The user already named these; keep them: parts "
            + ", ".join(hints.you_parts)
            + "; dimensions "
            + ", ".join(hints.you_dimensions)
        )
    if hints.removed:
        lines.append(
            "Never propose any of these (the user removed them): " + ", ".join(hints.removed)
        )
    if hints.parent_dimensions:
        lines.append(
            "This item was derived from another item. Reuse these exact dimension keys and "
            "labels where they still apply: "
            + "; ".join(
                f"{d.get('key')} ({d.get('label')}, {d.get('type')}"
                + (f", part {d['part']}" if d.get("part") else "")
                + f", {d.get('kind')})"
                for d in hints.parent_dimensions
            )
        )
    if board_context:
        lines.append(f"Board context: {board_context}")
    if is_text:
        lines.append(f"The text:\n{TEXT_OPEN}\n{content.text}\n{TEXT_CLOSE}")
    return "\n".join(lines)


def _token(*candidates: object) -> str:
    for c in candidates:
        if isinstance(c, str) and (t := canonical_token(c)):
            return t
    return ""


def _clean_part(raw: Any, content_type: str, text_len: int) -> PartOut | None:
    if not isinstance(raw, dict):
        return None
    raw = {**raw, "key": _token(raw.get("key"), raw.get("label"))}
    want = {"text": "text_range", "ui": "box", "image": "mask"}[content_type]
    if raw.get("region_kind") != want:
        return None
    if want == "mask":
        raw["region"] = None
    try:
        part = PartOut.model_validate(raw)
        if want == "box":
            Region(kind="box", box=part.region)  # type: ignore[arg-type]
        elif want == "text_range":
            if not isinstance(part.region, list) or len(part.region) != 2:
                return None
            start = max(0, int(part.region[0]))
            end = min(text_len, int(part.region[1]))
            Region(kind="text_range", range=[start, end])
            part.region = [start, end]
    except (ValidationError, ValueError, TypeError):
        return None
    return part if part.key else None


def _clean_dimension(raw: Any, part_keys: set[str]) -> DimensionOut | None:
    if not isinstance(raw, dict):
        return None
    part = raw.get("part")
    raw = {
        **raw,
        "key": _token(raw.get("key"), raw.get("label")),
        "part": (_token(part) or None) if isinstance(part, str) else None,
    }
    if raw["part"] is not None and raw["part"] not in part_keys:
        return None
    try:
        dim = DimensionOut.model_validate(raw)
    except ValidationError:
        return None
    return dim if dim.key else None


def run_analyser(content: ItemContent, board_context: str, hints: Hints) -> Analysis:
    prompt = build_prompt(content, board_context, hints)
    images = [content.image] if content.image is not None else []
    raw = get_reasoning(get_settings()).structured(images, ANALYSIS_SCHEMA, prompt)
    if not isinstance(raw, dict):
        raw = {}

    is_text = content.text is not None
    declared = raw.get("content_type")
    content_type = "text" if is_text else ("ui" if declared == "ui" else "image")
    if hints.content_type in ("image", "ui", "text") and not is_text:
        content_type = hints.content_type
    text_len = len(content.text or "")

    parts: list[PartOut] = []
    for p in raw.get("parts") or []:
        if (part := _clean_part(p, content_type, text_len)) is not None and all(
            part.key != q.key for q in parts
        ):
            parts.append(part)
    parts = parts[:MAX_PARTS]

    keys = {p.key for p in parts}
    dims: list[DimensionOut] = []
    for d in raw.get("dimensions") or []:
        if (dim := _clean_dimension(d, keys)) is not None and all(
            (dim.key, dim.part) != (q.key, q.part) for q in dims
        ):
            dims.append(dim)
    dims = dims[:MAX_DIMENSIONS]

    summary = raw.get("summary")
    return Analysis(
        content_type=content_type,  # type: ignore[arg-type]
        summary=summary if isinstance(summary, str) else "",
        parts=parts,
        dimensions=dims,
    )
