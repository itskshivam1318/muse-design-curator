from pathlib import Path

from sqlalchemy import create_engine, text

from alembic import command
from app.db.session import alembic_config, migration_transaction, run_migrations


def _insert_item(c, **kw) -> None:  # type: ignore[no-untyped-def]
    row = {
        "id": "itm_x", "board_id": "brd_x", "kind": "image", "origin": "upload",
        "rights_status": "user_supplied", "captured_at": "t", "parse_status": "pending",
        "role": "reference", "x": 0, "y": 0, "w": 0, "h": 0, "z": 0,
        "parse_attempts": 0, "created_at": "t", **kw,
    }  # fmt: skip
    c.execute(
        text(
            f"INSERT INTO board_items ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"
        ),
        row,
    )


def _populate(engine) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        _insert_item(c)
        c.execute(
            text(
                "INSERT INTO explorations (id, board_id, item_id, key, created_at) "
                "VALUES ('exp_x', 'brd_x', 'itm_x', 'k', 't')"
            )
        )
        c.execute(
            text(
                "INSERT INTO explore_options (id, exploration_id, batch, name, description, "
                "distance, edit_prompt, status, created_at) "
                "VALUES ('opt_x', 'exp_x', 1, 'n', 'd', 'near', 'p', 'open', 't')"
            )
        )
        _insert_item(
            c, id="itm_gen", origin="generated", rights_status="generated",
            explore_option_id="opt_x",
        )  # fmt: skip


def test_upgrade_on_populated_db(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine, "0006_explore")
    _populate(engine)
    run_migrations(engine)
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM explore_options")).scalar() == 1
        assert c.execute(text("SELECT staged FROM board_items WHERE staged = 0")).fetchall() == [
            (0,),
            (0,),
        ]
        assert c.execute(text("SELECT kept_item_id FROM explore_options")).scalar() is None
        gen = c.execute(
            text("SELECT explore_option_id FROM board_items WHERE id='itm_gen'")
        ).scalar()
        assert gen == "opt_x"
        _insert_item(c, id="itm_note", kind="note", origin="note")
        c.execute(text("UPDATE explore_options SET status='kept'"))
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0007_round2"
    engine.dispose()


def test_downgrade_roundtrip(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'r.sqlite'}")
    run_migrations(engine)
    _populate(engine)
    cfg = alembic_config()
    with migration_transaction(engine) as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0006_explore")
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0006_explore"
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 2
    run_migrations(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0007_round2"
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 2
    engine.dispose()
