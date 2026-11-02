import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Board, BoardItem, ItemPart


def _item(session: Session) -> BoardItem:
    b = Board(title="t")
    session.add(b)
    session.flush()
    it = BoardItem(board_id=b.id, kind="image", origin="upload")
    session.add(it)
    session.flush()
    return it


def test_part_key_unique_per_item(session: Session) -> None:
    it = _item(session)
    session.add(
        ItemPart(item_id=it.id, key="hands", label="Hands", region_kind="mask", source="ai")
    )
    session.flush()
    assert session.query(ItemPart).one().id.startswith("part_")
    session.add(
        ItemPart(item_id=it.id, key="hands", label="Hands", region_kind="box", source="you")
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_region_kind_checked(session: Session) -> None:
    it = _item(session)
    session.add(ItemPart(item_id=it.id, key="x", label="X", region_kind="blob", source="ai"))
    with pytest.raises(IntegrityError):
        session.flush()
