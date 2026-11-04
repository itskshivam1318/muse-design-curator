from sqlalchemy.orm import Session

from app.db.repos import agent as agent_repo
from app.db.repos import boards as boards_repo


def _run(session: Session, source: str = "muse", status: str = "running") -> tuple[str, str]:
    board = boards_repo.create(session, "B")
    run = agent_repo.create_run(session, board.id, source, "goal", [])
    run.status = status
    session.flush()
    return board.id, run.id


def test_message_round_trip(session: Session) -> None:
    board_id, run_id = _run(session)
    agent_repo.add_message(session, run_id, board_id, "person", "make it warmer")
    agent_repo.add_message(session, run_id, board_id, "question", "which room?", {"options": ["a"]})
    got = agent_repo.messages(session, run_id)
    assert [m.role for m in got] == ["person", "question"]
    d = agent_repo.message_to_dict(got[1])
    assert set(d) == {"id", "run_id", "role", "text", "data", "answered", "created_at"}
    assert d["data"] == {"options": ["a"]} and d["answered"] is False


def test_open_question_latest_unanswered(session: Session) -> None:
    board_id, run_id = _run(session)
    assert agent_repo.open_question(session, run_id) is None
    first = agent_repo.add_message(session, run_id, board_id, "question", "one?")
    second = agent_repo.add_message(session, run_id, board_id, "question", "two?")
    assert agent_repo.open_question(session, run_id) == second
    second.answered = True
    session.flush()
    assert agent_repo.open_question(session, run_id) == first


def test_open_run_includes_waiting(session: Session) -> None:
    board_id, run_id = _run(session, status="waiting")
    run = agent_repo.open_run(session, board_id)
    assert run is not None and run.id == run_id


def test_open_run_filters_by_source(session: Session) -> None:
    board_id, run_id = _run(session, source="muse")
    assert agent_repo.open_run(session, board_id, "mcp") is None
    found = agent_repo.open_run(session, board_id, "muse")
    assert found is not None and found.id == run_id
