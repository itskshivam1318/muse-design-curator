"""Grow a closed enum's vocabulary with a visualized option's value, as a new lens version."""

import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import events
from app.api.schemas import board_to_dict
from app.config import get_settings
from app.db.repos import boards as boards_repo
from app.db.repos import lenses as lenses_repo
from app.db.session import after_commit
from app.domain.attributes import Value
from app.domain.kinds import EnumSpec, check_token
from app.domain.lens import LensSpec, validate_lens

log = logging.getLogger(__name__)


def add_vocabulary(session: Session, board_id: str, key: str, value: Value) -> bool:
    """True when `value` was appended to the board lens's closed enum `key` (a new confirmed
    lens version, now the board's). Open vocabularies, other kinds and known values: False."""
    board = boards_repo.get(session, board_id)
    row = lenses_repo.get(session, board.lens_id) if board and board.lens_id else None
    if board is None or row is None or not isinstance(value, str):
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
    latest = lenses_repo.latest(session, board_id, row.domain)
    version = (latest.version if latest else 0) + 1
    grown = attr.model_copy(update={"vocabulary": [*vocab, token]})
    data = spec.model_dump(mode="json")
    data["id"] = f"{row.domain}@{version}"
    data["origin"] = "edited"
    data["attributes"] = [
        (grown if a.key == key else a).model_dump(mode="json") for a in spec.attributes
    ]
    try:
        edited = validate_lens(LensSpec.model_validate(data), get_settings().SHAPE_KIND_ENABLED)
    except (ValidationError, ValueError) as exc:
        log.warning("could not add %r to %s on board %s: %s", token, key, board_id, exc)
        return False
    saved = lenses_repo.save(
        session, board_id, row.domain, "edited", edited.model_dump(mode="json"), status="confirmed"
    )
    board.lens_id = saved.id
    session.flush()
    event = {"board": board_to_dict(board)}
    after_commit(session, lambda: events.publish(board_id, "board.updated", event))
    return True
