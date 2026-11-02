"""Explore one of an item's own dimensions into named text options, stored per (item, key).

Each call asks the reasoning provider for a batch, cleans it (junk dropped, names deduped
case-insensitively across the exploration, keeps limited to the item's own dimensions) and
stores it as the exploration's next batch. Nothing is written until the model has answered.
"""

from functools import partial
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.analysis import limits
from app.analysis.context import board_context
from app.analysis.spec import dimension_type, spec_for, spec_for_key
from app.config import get_settings
from app.db.models import BoardItem, Exploration, ExploreOption, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import explore as explore_repo
from app.db.session import after_commit
from app.domain.attributes import (
    Value,
    _coerce_bool,
    canonical_token,
    validate_value,
)
from app.domain.kinds import AttributeSpec
from app.errors import AppError
from app.explore.prompts import build_explore_prompt
from app.extraction.service import _image_for, _require_item, current_lens
from app.notes.service import with_notes
from app.providers import get_reasoning
from app.providers.reliability import ModelError
from app.runs.orchestrator import record_of

Mode = Literal["initial", "more", "further"]
DISTANCES = ("near", "bold", "wild")
MAX_OPTIONS = 10
EVENT = "explore.updated"
KEEP_REST = "Keep everything else exactly the same."


def require_enabled() -> None:
    if not get_settings().EXPLORE_ENABLED:
        raise AppError(503, "FEATURE_OFF", "Explore is turned off")


def coerce_option_value(spec: AttributeSpec, raw: str, *, current: Value) -> Value | None:
    """The option's value typed for the attribute's kind, or None when it does not fit.

    Enum and text values are tokens even outside a closed vocabulary (explore goes beyond it).
    A boolean option is about how the feature is done: the model's true/false if it gave one,
    else the current state.
    """
    if spec.kind == "shape":
        return None
    if spec.kind == "boolean":
        parsed = _coerce_bool(raw)
        if parsed is not None:
            return parsed
        return current if isinstance(current, bool) else None
    if spec.kind in ("enum", "text"):
        return canonical_token(raw) or None
    if spec.kind == "color":
        return " ".join(raw.lower().split()) or None
    return validate_value(raw, spec)  # number within min/max, ordinal on the scale


def _text(raw: Any) -> str:
    return " ".join(raw.split()) if isinstance(raw, str) else ""


def _with_keep(prompt: str) -> str:
    """The edit prompt ending with KEEP_REST: without it image models restyle the whole image."""
    if prompt.endswith(KEEP_REST):
        return prompt
    return f"{prompt.rstrip()}{'' if prompt.endswith(('.', '!', '?')) else '.'} {KEEP_REST}"


def _clean(
    raw: Any, spec: AttributeSpec, current: Value, known: set[str], seen: set[str]
) -> list[dict[str, Any]]:
    """Valid, new options from the model's answer, at most MAX_OPTIONS. Updates `seen`."""
    batch = raw.get("options") if isinstance(raw, dict) else None
    out: list[dict[str, Any]] = []
    for o in batch if isinstance(batch, list) else []:
        if not isinstance(o, dict):
            continue
        name = _text(o.get("name"))
        distance = _text(o.get("distance")).lower()
        if not name or name.lower() in seen or distance not in DISTANCES:
            continue
        value = coerce_option_value(spec, str(o.get("value") or ""), current=current)
        if value is None and spec.kind != "boolean":
            continue
        raw_keeps = o.get("keeps")
        keeps: list[str] = []
        for k in raw_keeps if isinstance(raw_keeps, list) else []:
            if isinstance(k, str) and k in known and k != spec.key and k not in keeps:
                keeps.append(k)
        description = _text(o.get("description"))
        # the description's own full stop would double the sentence's
        detail = f"{name}: {description.rstrip('.')}" if description.rstrip(".") else name
        edit = _with_keep(_text(o.get("edit_prompt")) or f"Change only {spec.label} to {detail}.")
        seen.add(name.lower())
        out.append({
            "name": name, "description": description, "distance": distance,
            "value_json": value, "keeps_json": keeps, "edit_prompt": edit,
        })  # fmt: skip
        if len(out) == MAX_OPTIONS:
            break
    return out


def dimensions(session: Session, item_id: str) -> list[ItemAttribute]:
    """The item's own dimensions, the ones the user removed left out (stale ones kept)."""
    return [r for r in attrs_repo.for_item(session, item_id) if not r.removed]


def is_held(row: ItemAttribute) -> bool:
    """A dimension still found on the item: not removed and not stale."""
    return not row.removed and row.status != "stale"


def _part_label(session: Session, row: ItemAttribute) -> str | None:
    if not row.part:
        return None
    part = session.scalar(
        select(ItemPart).where(
            ItemPart.item_id == row.item_id, ItemPart.key == row.part, ItemPart.removed.is_(False)
        )
    )
    return part.label if part is not None else row.part.replace("_", " ")


def _find(session: Session, item_id: str, key: str) -> Exploration | None:
    return session.scalar(
        select(Exploration).where(Exploration.item_id == item_id, Exploration.key == key)
    )


def visible(session: Session, exploration_id: str) -> list[ExploreOption]:
    return [o for o in explore_repo.options(session, exploration_id) if o.status != "dismissed"]


def publish_later(session: Session, e: Exploration) -> None:
    opts = visible(session, e.id)
    data = explore_repo.exploration_to_dict(
        e, opts, explore_repo.takes(session, [o.id for o in opts])
    )
    after_commit(session, partial(events.publish, e.board_id, EVENT, data))


def explore(
    session: Session,
    item_id: str,
    key: str,
    *,
    steer: str | None,
    parent_option_id: str | None,
    mode: Mode,
) -> tuple[Exploration, list[ExploreOption]]:
    """Add a batch of options to the item's exploration of `key`; returns its visible options."""
    require_enabled()
    item = _require_item(session, item_id)
    if item.staged:
        raise AppError(404, "ITEM_NOT_FOUND", "Item not found")
    rows = dimensions(session, item.id)
    row = next((r for r in rows if r.key == key), None)
    found = _find(session, item.id, key)
    # a legacy exploration (made under a lens) whose key has no row on the item: abstract
    legacy = found is not None and not any(
        r.key == key for r in attrs_repo.for_item(session, item.id)
    )
    if row is None and not legacy:
        raise AppError(400, "DIMENSION_NOT_ON_ITEM", f"{key} is not a dimension of this item")
    lens = current_lens(session, item.board_id)
    spec = spec_for(row, lens) if row is not None else spec_for_key(key, lens)
    if spec.kind == "shape":
        raise AppError(400, "KIND_NOT_EXPLORABLE", "Shape attributes cannot be explored")

    existing = explore_repo.options(session, found.id) if found else []
    parent = None
    if parent_option_id is not None:
        parent = next((o for o in existing if o.id == parent_option_id), None)
        if parent is None:
            raise AppError(404, "OPTION_NOT_FOUND", "Option not found in this exploration")

    attributes = [record_of(r) for r in rows if is_held(r)]
    held = {a.key for a in attributes}
    current: Value = row.value_json if row is not None else None
    board = boards_repo.get(session, item.board_id)
    context = with_notes(session, item.board_id, board_context(session, item.board_id))
    steer = _text(steer) or None
    prompt = build_explore_prompt(
        spec=spec, current=current, attributes=attributes,
        board_title=board.title if board else "", board_context=context,
        existing_names=[o.name for o in existing],
        parent=(
            {"name": parent.name, "description": parent.description,
             "distance": parent.distance, "value": parent.value_json}
            if parent else None
        ),
        steer=steer, mode=mode,
        dimension_prompt=row.prompt if row and dimension_type(row) == "abstract" else None,
        part_label=_part_label(session, row) if row and dimension_type(row) == "physical" else None,
    )  # fmt: skip
    images: list[bytes]
    if item.kind == "note":  # a text item: the options are read from its words
        images = []
        prompt += f"\n\nThere is no image: the item is this text.\n<<<TEXT\n{item.note_text or ''}\nTEXT>>>"
    else:
        images = [_image_for(session, item)[0]]
    limits.check_and_count(item.board_id, "analyse")
    try:
        raw = get_reasoning(get_settings()).explore_options(images, prompt)
    except ModelError as exc:
        raise AppError(502, exc.code, f"The model could not explore: {exc.message}") from exc

    seen = {o.name.lower() for o in existing}
    cleaned = _clean(raw, spec, current, held, seen)
    if not cleaned:
        raise AppError(502, "EXPLORE_EMPTY", "The model returned no usable new options")

    e = found or explore_repo.get_or_create(session, item.board_id, item.id, key)
    batch = explore_repo.next_batch(session, e.id)
    explore_repo.add_options(session, e.id, [
        {**r, "batch": batch, "steer": steer, "parent_option_id": parent_option_id} for r in cleaned
    ])  # fmt: skip
    publish_later(session, e)
    return e, visible(session, e.id)


def resting_status(session: Session, option_id: str) -> str:
    """An option not dismissed or busy: kept while a take is kept, visualized once it has an
    image on the board, else open."""
    o = explore_repo.get_option(session, option_id)
    if o is not None and o.kept_item_id is not None:
        kept = session.get(BoardItem, o.kept_item_id)
        if kept is not None and kept.removed_at is None:
            return "kept"
    return "visualized" if explore_repo.has_generated(session, option_id) else "open"


def update_option(session: Session, option_id: str, **fields: Any) -> ExploreOption:
    """Dismiss, restore or move an option; publishes the exploration.

    Restoring an option whose visualize job still holds its claim (it was dismissed mid-job, or
    is still running) keeps it `visualizing`, so the claim is not freed for a second job."""
    require_enabled()
    o = explore_repo.get_option(session, option_id)
    if o is None:
        raise AppError(404, "OPTION_NOT_FOUND", "Option not found")
    if fields.get("status") == "open":
        busy = o.status == "visualizing" or o.visualize_claimed_at is not None
        fields["status"] = "visualizing" if busy else resting_status(session, option_id)
    o = explore_repo.update_option(session, option_id, **fields)
    assert o is not None
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    publish_later(session, e)
    return o
