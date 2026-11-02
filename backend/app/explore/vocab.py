"""Grow a closed enum's vocabulary with a visualized option's value: the item dimension's own
spec, or the board lens (as a new lens version) for a dimension that has none."""

import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import events
from app.analysis.spec import spec_for
from app.api.schemas import board_to_dict
from app.config import get_settings
from app.db.models import Board, ItemAttribute, Lens
from app.db.repos import boards as boards_repo
from app.db.repos import lenses as lenses_repo
from app.db.session import after_commit
from app.domain.attributes import Value
from app.domain.kinds import AttributeSpec, EnumSpec, check_token
from app.domain.lens import LensSpec, validate_lens

log = logging.getLogger(__name__)


def _base(session: Session, board: Board) -> Lens | None:
    """The newest confirmed lens in the domain of the board's lens, read at write time rather
    than trusting a possibly stale `lens_id`, so a token another job just added is kept."""
    current = lenses_repo.get(session, board.lens_id) if board.lens_id else None
    if current is None:
        return None
    q = (
        select(Lens)
        .where(Lens.board_id == board.id, Lens.domain == current.domain, Lens.status == "confirmed")
        .order_by(Lens.version.desc())
        .limit(1)
    )
    return session.scalar(q) or current


def _add(session: Session, board_id: str, key: str, value: Value) -> bool:
    board = boards_repo.get(session, board_id)
    if board is None or not isinstance(value, str):
        return False
    session.refresh(board)
    row = _base(session, board)
    if row is None:
        return False
    spec = LensSpec.model_validate(row.spec_json)
    attr = next((a for a in spec.attributes if a.key == key), None)
    grown = _grown(attr, value) if attr is not None else None
    if grown is None:
        return False
    data = spec.model_dump(mode="json")
    data["origin"] = "edited"
    data["attributes"] = [
        (grown if a.key == key else a).model_dump(mode="json") for a in spec.attributes
    ]
    try:
        edited = validate_lens(LensSpec.model_validate(data), get_settings().SHAPE_KIND_ENABLED)
    except (ValidationError, ValueError) as exc:
        log.warning("could not add %r to %s on board %s: %s", value, key, board_id, exc)
        return False
    out = edited.model_dump(mode="json")
    saved = lenses_repo.save(session, board_id, row.domain, "edited", out, status="confirmed")
    saved.spec_json = {**out, "id": f"{row.domain}@{saved.version}"}  # the version just saved
    board.lens_id = saved.id
    session.flush()
    event = {"board": board_to_dict(board)}
    after_commit(session, lambda: events.publish(board_id, "board.updated", event))
    return True


def _grown(spec: AttributeSpec, value: Value) -> EnumSpec | None:
    """`spec` with `value` appended when it is a closed enum that lacks it, else None."""
    if not isinstance(spec, EnumSpec) or spec.open_vocabulary or not isinstance(value, str):
        return None
    try:
        token = check_token(value)
    except ValueError:
        return None
    vocab = spec.vocabulary or []
    if token in vocab:
        return None
    return spec.model_copy(update={"vocabulary": [*vocab, token]})


def _add_to_item(session: Session, row: ItemAttribute, value: Value) -> bool:
    """Grow the item's own stored spec; the board lens is not this dimension's authority."""
    grown = _grown(spec_for(row), value)
    if grown is None:
        return False
    row.spec_json = grown.model_dump(mode="json")
    session.flush()
    return True


def add_vocabulary(
    session: Session, board_id: str, key: str, value: Value, *, item_id: str | None = None
) -> bool:
    """True when `value` was appended to the closed enum `key`. The dimension's spec is
    resolved as `spec_for` does: an item dimension with its own stored spec (`item_id` given)
    grows that spec; otherwise the board lens's attribute grows, as a new confirmed lens
    version, now the board's. Open vocabularies, other kinds and known values: False.

    Another writer can take the same lens version at the same moment; then the session is
    rolled back (the caller must have nothing pending) and the add is tried once more.
    """
    if item_id is not None:
        row = session.scalar(
            select(ItemAttribute).where(ItemAttribute.item_id == item_id, ItemAttribute.key == key)
        )
        if row is not None and row.spec_json:
            return _add_to_item(session, row, value)
    try:
        return _add(session, board_id, key, value)
    except IntegrityError:
        session.rollback()
        return _add(session, board_id, key, value)
