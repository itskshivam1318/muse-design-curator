from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BoardItem, Exploration, ExploreOption


def get_or_create(session: Session, board_id: str, item_id: str, key: str) -> Exploration:
    found = session.scalar(
        select(Exploration).where(Exploration.item_id == item_id, Exploration.key == key)
    )
    if found:
        return found
    e = Exploration(board_id=board_id, item_id=item_id, key=key)
    session.add(e)
    session.flush()
    return e


def add_options(
    session: Session, exploration_id: str, rows: list[dict[str, Any]]
) -> list[ExploreOption]:
    out = [ExploreOption(exploration_id=exploration_id, **r) for r in rows]
    session.add_all(out)
    session.flush()
    return out


def options(session: Session, exploration_id: str) -> list[ExploreOption]:
    q = select(ExploreOption).where(ExploreOption.exploration_id == exploration_id)
    return list(session.scalars(q.order_by(ExploreOption.id)))


def get_option(session: Session, option_id: str) -> ExploreOption | None:
    return session.get(ExploreOption, option_id)


def for_board(session: Session, board_id: str) -> list[tuple[Exploration, list[ExploreOption]]]:
    q = (
        select(Exploration)
        .join(BoardItem, BoardItem.id == Exploration.item_id)
        .where(Exploration.board_id == board_id, BoardItem.removed_at.is_(None))
        .order_by(Exploration.id)
    )
    out = []
    for e in session.scalars(q):
        opts = [o for o in options(session, e.id) if o.status != "dismissed"]
        out.append((e, opts))
    return out


def update_option(session: Session, option_id: str, **fields: Any) -> ExploreOption | None:
    o = session.get(ExploreOption, option_id)
    if o is None:
        return None
    for k, v in fields.items():
        setattr(o, k, v)
    session.flush()
    return o


def has_generated(session: Session, option_id: str) -> bool:
    """True while a generated item made from this option is on the board."""
    q = select(BoardItem.id).where(
        BoardItem.explore_option_id == option_id, BoardItem.removed_at.is_(None)
    )
    return session.scalar(q.limit(1)) is not None


def generated_count(session: Session, option_id: str) -> int:
    """How many generated items made from this option are on the board."""
    q = select(func.count(BoardItem.id)).where(
        BoardItem.explore_option_id == option_id, BoardItem.removed_at.is_(None)
    )
    return session.scalar(q) or 0


def next_batch(session: Session, exploration_id: str) -> int:
    top = session.scalar(
        select(func.max(ExploreOption.batch)).where(ExploreOption.exploration_id == exploration_id)
    )
    return (top or 0) + 1


def option_to_dict(o: ExploreOption) -> dict[str, Any]:
    return {
        "id": o.id, "exploration_id": o.exploration_id,
        "parent_option_id": o.parent_option_id, "batch": o.batch, "steer": o.steer,
        "name": o.name, "description": o.description, "distance": o.distance,
        "value": o.value_json, "keeps": o.keeps_json, "edit_prompt": o.edit_prompt,
        "status": o.status, "last_error": o.last_error, "x": o.x, "y": o.y,
        "created_at": o.created_at,
    }  # fmt: skip


def exploration_to_dict(e: Exploration, opts: list[ExploreOption]) -> dict[str, Any]:
    return {
        "id": e.id, "board_id": e.board_id, "item_id": e.item_id, "key": e.key,
        "created_at": e.created_at, "options": [option_to_dict(o) for o in opts],
    }  # fmt: skip
