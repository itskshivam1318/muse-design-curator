"""Explore one attribute of an item into named text options, stored per (item, attribute).

Each call asks the reasoning provider for a batch, cleans it (junk dropped, names deduped
case-insensitively across the exploration, keeps limited to the lens keys) and stores it as the
exploration's next batch. Nothing is written until the model has answered.
"""

from functools import partial
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.config import get_settings
from app.db.models import Exploration, ExploreOption
from app.db.repos import boards as boards_repo
from app.db.repos import explore as explore_repo
from app.db.session import after_commit
from app.domain.attributes import AttributeRecord, Value, canonical_token, validate_value
from app.domain.kinds import AttributeSpec
from app.errors import AppError
from app.explore.prompts import build_explore_prompt
from app.extraction.service import _image_for, _require_item, current_lens
from app.providers import get_reasoning
from app.providers.reliability import ModelError
from app.runs.orchestrator import source_records

Mode = Literal["initial", "more", "further"]
DISTANCES = ("near", "bold", "wild")
MAX_OPTIONS = 10
EVENT = "explore.updated"


def require_enabled() -> None:
    if not get_settings().EXPLORE_ENABLED:
        raise AppError(503, "FEATURE_OFF", "Explore is turned off")


def coerce_option_value(spec: AttributeSpec, raw: str, *, current: Value) -> Value | None:
    """The option's value typed for the attribute's kind, or None when it does not fit.

    Enum and text values are tokens even outside a closed vocabulary (explore goes beyond it).
    A boolean option keeps the feature's other state: options are about how it is done.
    """
    if spec.kind == "shape":
        return None
    if spec.kind == "boolean":
        return (not current) if isinstance(current, bool) else None
    if spec.kind in ("enum", "text"):
        return canonical_token(raw) or None
    if spec.kind == "color":
        return " ".join(raw.lower().split()) or None
    return validate_value(raw, spec)  # number within min/max, ordinal on the scale


def _missing(spec: AttributeSpec) -> AttributeRecord:
    return AttributeRecord(
        key=spec.key, label=spec.label, category=spec.category, kind=spec.kind, part=spec.part,
        value=None, confidence=0.0, status="missing", source="model",
    )  # fmt: skip


def _text(raw: Any) -> str:
    return " ".join(raw.split()) if isinstance(raw, str) else ""


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
        edit = _text(o.get("edit_prompt")) or (
            f"Change only the {spec.label} to {name}. Keep everything else exactly the same."
        )
        seen.add(name.lower())
        out.append({
            "name": name, "description": _text(o.get("description")), "distance": distance,
            "value_json": value, "keeps_json": keeps, "edit_prompt": edit,
        })  # fmt: skip
        if len(out) == MAX_OPTIONS:
            break
    return out


def _find(session: Session, item_id: str, key: str) -> Exploration | None:
    return session.scalar(
        select(Exploration).where(Exploration.item_id == item_id, Exploration.key == key)
    )


def visible(session: Session, exploration_id: str) -> list[ExploreOption]:
    return [o for o in explore_repo.options(session, exploration_id) if o.status != "dismissed"]


def publish_later(session: Session, e: Exploration) -> None:
    data = explore_repo.exploration_to_dict(e, visible(session, e.id))
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
    lens = current_lens(session, item.board_id)
    if lens is None:
        raise AppError(409, "LENS_REQUIRED", "The board needs a lens before exploring")
    spec = next((a for a in lens.attributes if a.key == key), None)
    if spec is None:
        raise AppError(400, "ATTRIBUTE_NOT_IN_LENS", f"{key} is not an attribute of this lens")
    if spec.kind == "shape":
        raise AppError(400, "KIND_NOT_EXPLORABLE", "Shape attributes cannot be explored")

    found = _find(session, item.id, key)
    existing = explore_repo.options(session, found.id) if found else []
    parent = None
    if parent_option_id is not None:
        parent = next((o for o in existing if o.id == parent_option_id), None)
        if parent is None:
            raise AppError(404, "OPTION_NOT_FOUND", "Option not found in this exploration")

    have = {r.key: r for r in source_records(session, item.id)}
    attributes = [have.get(a.key) or _missing(a) for a in lens.attributes]
    current = have[key].value if key in have else None
    board = boards_repo.get(session, item.board_id)
    steer = _text(steer) or None
    prompt = build_explore_prompt(
        spec=spec, current=current, attributes=attributes,
        board_title=board.title if board else "", board_context=board.context if board else "",
        existing_names=[o.name for o in existing],
        parent=(
            {"name": parent.name, "description": parent.description,
             "distance": parent.distance, "value": parent.value_json}
            if parent else None
        ),
        steer=steer, mode=mode,
    )  # fmt: skip
    image, _sha = _image_for(session, item)
    try:
        raw = get_reasoning(get_settings()).explore_options([image], prompt)
    except ModelError as exc:
        raise AppError(502, exc.code, f"The model could not explore: {exc.message}") from exc

    seen = {o.name.lower() for o in existing}
    rows = _clean(raw, spec, current, {a.key for a in lens.attributes}, seen)
    if not rows:
        raise AppError(502, "EXPLORE_EMPTY", "The model returned no usable new options")

    e = found or explore_repo.get_or_create(session, item.board_id, item.id, key)
    batch = explore_repo.next_batch(session, e.id)
    explore_repo.add_options(session, e.id, [
        {**r, "batch": batch, "steer": steer, "parent_option_id": parent_option_id} for r in rows
    ])  # fmt: skip
    publish_later(session, e)
    return e, visible(session, e.id)


def update_option(session: Session, option_id: str, **fields: Any) -> ExploreOption:
    """Dismiss, restore or move an option; publishes the exploration."""
    require_enabled()
    o = explore_repo.update_option(session, option_id, **fields)
    if o is None:
        raise AppError(404, "OPTION_NOT_FOUND", "Option not found")
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    publish_later(session, e)
    return o
