from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.models import BoardItem
from app.db.repos import boards, explore, items
from app.db.session import run_migrations


def _setup(session: Session) -> tuple[str, str]:
    b = boards.create(session, title="b")
    it = items.create(session, board_id=b.id, kind="image", origin="upload", sha256="a" * 64)
    return b.id, it.id


def _row(name: str) -> dict[str, object]:
    return {"name": name, "description": "d", "distance": "near", "value_json": {"v": 1},
            "keeps_json": ["k"], "edit_prompt": "p", "batch": 1}  # fmt: skip


def test_get_or_create_is_unique_per_item_key(session: Session) -> None:
    b, i = _setup(session)
    a = explore.get_or_create(session, b, i, "palette")
    assert explore.get_or_create(session, b, i, "palette").id == a.id
    assert explore.get_or_create(session, b, i, "other").id != a.id


def test_for_board_skips_removed_source_and_dismissed(session: Session) -> None:
    b, i = _setup(session)
    e = explore.get_or_create(session, b, i, "k")
    o1, o2 = explore.add_options(session, e.id, [_row("one"), _row("two")])
    explore.update_option(session, o2.id, status="dismissed")
    got = explore.for_board(session, b)
    assert [(x.id, [o.id for o in os]) for x, os in got] == [(e.id, [o1.id])]
    d = explore.exploration_to_dict(*got[0])
    assert d["options"][0]["value"] == {"v": 1} and d["options"][0]["keeps"] == ["k"]
    items.update(session, i, removed_at="2026-01-01T00:00:00.000+00:00")
    assert explore.for_board(session, b) == []
    assert explore.next_batch(session, e.id) == 2


def test_generated_item_allowed(session: Session) -> None:
    b, _ = _setup(session)
    session.add(
        BoardItem(
            board_id=b,
            kind="image",
            origin="generated",
            rights_status="generated",
            corpus_item_id=None,
        )
    )
    session.flush()


def test_migration_upgrade_head(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine)
    insp = inspect(engine)
    assert {"explorations", "explore_options"} <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("board_items")}
    assert {"explore_option_id", "generation_json", "check_json"} <= cols
    with engine.connect() as c:
        idx = c.execute(
            text("SELECT sql FROM sqlite_master WHERE name='uq_board_items_active_sha256'")
        ).scalar()
    assert idx and "WHERE" in idx
    engine.dispose()
