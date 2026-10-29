import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Board, BoardItem, BoardPlugin, PluginNode, PluginRun


def test_note_item_and_plugin_rows(session: Session) -> None:
    b = Board(title="t")
    session.add(b)
    session.flush()
    note = BoardItem(board_id=b.id, kind="note", origin="note", note_text="hello")
    session.add(note)
    session.add(BoardPlugin(board_id=b.id, plugin_id="p"))
    node = PluginNode(
        board_id=b.id, plugin_id="p", x=0, y=0, w=1, h=1,
        input_item_ids_json=[], params_json={},
    )  # fmt: skip
    session.add(node)
    session.flush()
    assert note.staged is False
    run = PluginRun(
        board_id=b.id, node_id=node.id, plugin_id="p", input_item_ids_json=[],
        params_json={}, status="queued",
    )  # fmt: skip
    session.add(run)
    session.commit()
    assert run.id.startswith("prun_") and node.id.startswith("node_")
    session.add(
        PluginRun(
            board_id=b.id, node_id=node.id, plugin_id="p", input_item_ids_json=[],
            params_json={}, status="bogus",
        )
    )  # fmt: skip
    with pytest.raises(IntegrityError):
        session.flush()
