"""Grow a closed enum's vocabulary with a visualized option's value, as a new lens version."""

import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import events
from app.api.schemas import board_to_dict
from app.config import get_settings
from app.db.models import Board, Lens
from app.db.repos import boards as boards_repo
from app.db.repos import lenses as lenses_repo
from app.db.session import after_commit
from app.domain.attributes import Value
from app.domain.kinds import EnumSpec, check_token
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
    if not isinstance(attr, EnumSpec) or attr.open_vocabulary:
        return False
    try:
        token = check_token(value)
    except ValueError:
        return False
    vocab = attr.vocabulary or []
    if token in vocab:
        return False
    grown = attr.model_copy(update={"vocabulary": [*vocab, token]})
    data = spec.model_dump(mode="json")
    data["origin"] = "edited"
    data["attributes"] = [
        (grown if a.key == key else a).model_dump(mode="json") for a in spec.attributes
    ]
    try:
        edited = validate_lens(LensSpec.model_validate(data), get_settings().SHAPE_KIND_ENABLED)
    except (ValidationError, ValueError) as exc:
        log.warning("could not add %r to %s on board %s: %s", token, key, board_id, exc)
        return False
    out = edited.model_dump(mode="json")
    saved = lenses_repo.save(session, board_id, row.domain, "edited", out, status="confirmed")
    saved.spec_json = {**out, "id": f"{row.domain}@{saved.version}"}  # the version just saved
    board.lens_id = saved.id
    session.flush()
    event = {"board": board_to_dict(board)}
    after_commit(session, lambda: events.publish(board_id, "board.updated", event))
    return True


def add_vocabulary(session: Session, board_id: str, key: str, value: Value) -> bool:
    """True when `value` was appended to the board lens's closed enum `key` (a new confirmed
    lens version, now the board's). Open vocabularies, other kinds and known values: False.

    Another writer can take the same lens version at the same moment; then the session is
    rolled back (the caller must have nothing pending) and the add is tried once more.
    """
    try:
        return _add(session, board_id, key, value)
    except IntegrityError:
        session.rollback()
        return _add(session, board_id, key, value)
