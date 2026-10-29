"""Keep one staged take of an option on the canvas; un-keep puts it back in the stage.

Takes are generated items made from an option. They start staged (hidden from the canvas, the
profile and the lens pool); keeping one un-stages it, and a second keep re-stages the first.
"""

from functools import partial

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import events
from app.api.schemas import item_to_dict
from app.board import profile_hook
from app.db.models import BoardItem, Exploration, ExploreOption
from app.db.repos import explore as explore_repo
from app.db.session import after_commit
from app.errors import AppError
from app.explore.service import publish_later, require_enabled, resting_status


def _option(session: Session, option_id: str) -> ExploreOption:
    o = explore_repo.get_option(session, option_id)
    if o is None:
        raise AppError(404, "OPTION_NOT_FOUND", "Option not found")
    return o


def _announce(session: Session, item: BoardItem) -> None:
    data = item_to_dict(item)
    after_commit(session, partial(events.publish, item.board_id, "item.updated", data))


def _finish(session: Session, o: ExploreOption, board_id: str) -> ExploreOption:
    session.flush()
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    publish_later(session, e)
    after_commit(session, partial(profile_hook.request_recompute, board_id))
    return o


def keep_take(
    session: Session, option_id: str, item_id: str, at: tuple[float, float] | None = None
) -> ExploreOption:
    """Make `item_id` the option's kept take: un-staged, at `at` when given. Every other
    take of the option goes back to the stage. Keeping the kept take again changes nothing but `at`."""
    require_enabled()
    o = _option(session, option_id)
    item = session.get(BoardItem, item_id)
    if item is None or item.removed_at is not None:
        raise AppError(404, "ITEM_NOT_FOUND", "Item not found")
    if item.explore_option_id != option_id:
        raise AppError(400, "NOT_A_TAKE", "This item is not a take of this option")
    if o.status == "dismissed":
        raise AppError(409, "OPTION_DISMISSED", "Restore this option before keeping a take")
    changed: list[BoardItem] = []
    others = list(
        session.scalars(
            select(BoardItem).where(
                BoardItem.explore_option_id == option_id,
                BoardItem.removed_at.is_(None),
                BoardItem.id != item.id,
                BoardItem.staged.is_(False),
            )
        )
    )
    session.execute(  # exactly one kept take: every other one goes back to the stage
        update(BoardItem)
        .where(
            BoardItem.explore_option_id == option_id,
            BoardItem.removed_at.is_(None),
            BoardItem.id != item.id,
            BoardItem.staged.is_(False),
        )
        .values(staged=True)
    )
    for other in others:
        session.refresh(other)
    changed.extend(others)
    if item.staged:
        item.staged = False
        changed.append(item)
    if at is not None and (item.x, item.y) != at:
        item.x, item.y = at
        if item not in changed:
            changed.append(item)
    o.kept_item_id = item.id
    if o.status != "visualizing":  # a running job holds its claim in the status; settle ends it
        o.status = "kept"
    session.flush()
    for c in changed:
        _announce(session, c)
    return _finish(session, o, item.board_id)


def unkeep(session: Session, option_id: str) -> ExploreOption:
    """Put the kept take back in the stage; a no-op when nothing is kept."""
    require_enabled()
    o = _option(session, option_id)
    if o.kept_item_id is None:
        return o
    item = session.get(BoardItem, o.kept_item_id)
    o.kept_item_id = None
    if o.status == "kept":
        o.status = "visualized" if explore_repo.has_generated(session, o.id) else "open"
    if item is None:
        return _finish(session, o, _exploration_board(session, o))
    if not item.staged:
        item.staged = True
        session.flush()
        _announce(session, item)
    return _finish(session, o, item.board_id)


def _exploration_board(session: Session, o: ExploreOption) -> str:
    e = session.get(Exploration, o.exploration_id)
    assert e is not None
    return e.board_id


def forget_deleted_take(session: Session, item: BoardItem) -> None:
    """After `item` is deleted: if it was its option's kept take, the option no longer keeps
    anything and rests at visualized (other takes remain) or open."""
    if item.explore_option_id is None:
        return
    o = explore_repo.get_option(session, item.explore_option_id)
    if o is None or o.kept_item_id != item.id:
        return
    o.kept_item_id = None
    if o.status == "kept":
        o.status = resting_status(session, o.id)
    _finish(session, o, item.board_id)
