from pathlib import Path

from sqlalchemy import create_engine, text

from alembic import command
from app.db.session import alembic_config, migration_transaction, run_migrations


def _cols(engine) -> set[str]:  # type: ignore[no-untyped-def]
    with engine.connect() as c:
        return {r[1] for r in c.exec_driver_sql("PRAGMA table_info(board_items)")}


def test_migration_0014_round_trip(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine, "0013_round3_plugins")
    assert "subject" not in _cols(engine)
    run_migrations(engine)
    assert "subject" in _cols(engine)
    with engine.begin() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "0014_item_subject"
        )
    cfg = alembic_config()
    with migration_transaction(engine) as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0013_round3_plugins")
    assert "subject" not in _cols(engine)
    run_migrations(engine)
    assert "subject" in _cols(engine)
