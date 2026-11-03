from sqlalchemy.orm import Session

from app.db.repos import agent, boards


def _board(session: Session) -> str:
    b = boards.create(session, title="t")
    session.flush()
    return b.id


def test_open_run_none_then_created(session: Session) -> None:
    bid = _board(session)
    assert agent.open_run(session, bid) is None
    run = agent.create_run(session, bid, "mcp", "find a mood", ["a", "b"])
    assert run.id.startswith("arun_")
    opened = agent.open_run(session, bid)
    assert opened is not None and opened.id == run.id
    d = agent.run_to_dict(run)
    assert d["deliverables"] == ["a", "b"] and d["finish_refusals"] == 0 and d["output"] is None


def test_add_step_turns_increment(session: Session) -> None:
    run = agent.create_run(session, _board(session), "muse", "g", [])
    for t in ("a", "b", "c"):
        agent.add_step(session, run.id, tool=t, args_json={}, ok=True, item_ids_json=[])
    got = agent.steps(session, run.id)
    assert [s.turn for s in got] == [1, 2, 3]
    assert got[0].id.startswith("astep_") and got[0].board_id == run.board_id
    assert agent.step_to_dict(got[0])["highlight"] is False


def test_open_run_ignores_done(session: Session) -> None:
    bid = _board(session)
    run = agent.create_run(session, bid, "mcp", "g", [])
    run.status = "done"
    session.flush()
    assert agent.open_run(session, bid) is None


def test_runs_newest_first(session: Session) -> None:
    bid = _board(session)
    first = agent.create_run(session, bid, "mcp", "one", [])
    second = agent.create_run(session, bid, "mcp", "two", [])
    assert [r.id for r in agent.runs(session, bid)] == [second.id, first.id]
