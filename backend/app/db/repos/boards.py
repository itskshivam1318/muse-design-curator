from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.ids import now_iso
from app.db.models import Board


def create(
    session: Session,
    title: str,
    context: str = "",
    domain: str | None = None,
    lens_id: str | None = None,
) -> Board:
    board = Board(title=title, context=context, domain=domain, lens_id=lens_id)
    session.add(board)
    session.flush()
    return board


def get(session: Session, board_id: str) -> Board | None:
    return session.get(Board, board_id)


def list_all(session: Session) -> list[Board]:
    return list(session.scalars(select(Board).order_by(Board.created_at.desc(), Board.id.desc())))


def update(session: Session, board_id: str, **fields: object) -> Board | None:
    board = session.get(Board, board_id)
    if board is None:
        return None
    for k, v in fields.items():
        setattr(board, k, v)
    board.updated_at = now_iso()
    session.flush()
    return board
