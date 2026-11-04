from pathlib import Path

from sqlalchemy import create_engine, text

from alembic import command
from app.db.session import alembic_config, migration_transaction, run_migrations

_ITEM = (
    "INSERT INTO board_items (id, board_id, kind, origin, rights_status, "
    "captured_at, parse_status, role, x, y, w, h, z, parse_attempts, created_at{extra}) "
    "VALUES ('{id}', 'brd_x', '{kind}', 'upload', 'user_supplied', 't', 'pending', "
    "'reference', 0, 0, 0, 0, 0, 0, 't'{val})"
)


def _cols(engine, table: str) -> set[str]:  # type: ignore[no-untyped-def]
    with engine.connect() as c:
        return {r[1] for r in c.exec_driver_sql(f"PRAGMA table_info({table})")}


def test_migration_0013_round_trip(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine, "0012_board_chat")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        c.execute(text(_ITEM.format(id="itm_a", kind="image", extra="", val="")))
    run_migrations(engine)
    assert "option_run_id" in _cols(engine, "board_items")
    assert "external_json" in _cols(engine, "plugin_runs")
    with engine.begin() as c:
        c.execute(
            text(_ITEM.format(id="itm_m", kind="model", extra=", option_run_id", val=", 'prun_1'"))
        )
        assert c.execute(text("SELECT option_run_id FROM board_items WHERE id='itm_a'")).scalar() is None
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0013_round3_plugins"
    cfg = alembic_config()
    with migration_transaction(engine) as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0012_board_chat")
    assert "option_run_id" not in _cols(engine, "board_items")
    assert "external_json" not in _cols(engine, "plugin_runs")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 1
    run_migrations(engine)
    assert "option_run_id" in _cols(engine, "board_items")
    engine.dispose()
