from pathlib import Path

from sqlalchemy import create_engine, text

from alembic import command
from app.db.session import alembic_config, migration_transaction, run_migrations


def _populate(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        c.execute(
            text(
                "INSERT INTO board_items (id, board_id, kind, origin, rights_status, "
                "captured_at, parse_status, role, x, y, w, h, z, parse_attempts, created_at) "
                "VALUES ('itm_x', 'brd_x', 'image', 'upload', 'user_supplied', 't', 'pending', "
                "'reference', 0, 0, 0, 0, 0, 0, 't')"
            )
        )


def test_upgrade_on_populated_db(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine, "0009_living_board")
    _populate(engine)
    run_migrations(engine)
    with engine.begin() as c:
        assert c.execute(text("SELECT put_source_item_id FROM board_items")).scalar() is None
        c.execute(
            text(
                "INSERT INTO board_items (id, board_id, kind, origin, rights_status, "
                "captured_at, parse_status, role, x, y, w, h, z, parse_attempts, created_at, "
                "put_source_item_id) VALUES ('itm_y', 'brd_x', 'image', 'generated', "
                "'generated', 't', 'pending', 'reference', 0, 0, 0, 0, 0, 0, 't', 'itm_x')"
            )
        )
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0012_board_chat"
    engine.dispose()


def test_downgrade_roundtrip(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'r.sqlite'}")
    run_migrations(engine)
    _populate(engine)
    cfg = alembic_config()
    with migration_transaction(engine) as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0009_living_board")
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0009_living_board"
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 1
    run_migrations(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0012_board_chat"
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 1
    engine.dispose()
