"""What the analyser is told about the board and the item. Task 9 fills in the learned parts."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.analysers import Hints
from app.db.models import ItemAttribute, ItemPart
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo

USER_SOURCES = ("you", "user")


def board_context(session: Session, board_id: str) -> str:
    board = boards_repo.get(session, board_id)
    return (board.context if board else "") or ""


def hints_for(session: Session, board_id: str, item_id: str) -> Hints:
    """The user's own parts and dimensions, what they removed, and the source item's dimensions."""
    hints = Hints.empty()
    parts = session.scalars(select(ItemPart).where(ItemPart.item_id == item_id))
    attrs = session.scalars(select(ItemAttribute).where(ItemAttribute.item_id == item_id))
    for p in parts:
        if p.removed:
            hints.removed.append(p.key)
        elif p.source == "you":
            hints.you_parts.append(p.key)
    for a in attrs:
        if a.removed:
            hints.removed.append(a.key)
        elif a.source in USER_SOURCES:
            hints.you_dimensions.append(a.key)
    item = items_repo.get(session, item_id)
    if item is not None and item.parent_item_id:
        parent_rows = session.scalars(
            select(ItemAttribute)
            .where(ItemAttribute.item_id == item.parent_item_id, ItemAttribute.removed.is_(False))
            .order_by(ItemAttribute.key)
        )
        hints.parent_dimensions = [
            {"key": r.key, "label": r.label, "type": r.dim_type, "part": r.part, "kind": r.kind}
            for r in parent_rows
        ]
    return hints


def refresh_learned(session: Session, board_id: str) -> list[str]:
    """Placeholder until the board's learned dimensions exist (Task 9)."""
    return []
