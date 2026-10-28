from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.db.models import (
    BoardItem,
    CorpusItem,
    Lens,
    RunCandidate,
    ValidationResult,
    VariationRun,
)
from app.db.repos import boards, explore, items
from app.db.session import BACKEND_DIR, run_migrations


def _setup(session: Session) -> tuple[str, str]:
    b = boards.create(session, title="b")
    it = items.create(session, board_id=b.id, kind="image", origin="upload", sha256="a" * 64)
    return b.id, it.id


def _row(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "d",
        "distance": "near",
        "value_json": {"v": 1},
        "keeps_json": ["k"],
        "edit_prompt": "p",
        "batch": 1,
    }


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


def _insert(c, **kw) -> None:  # type: ignore[no-untyped-def]
    row = {
        "id": "itm_x",
        "board_id": "brd_x",
        "kind": "image",
        "origin": "generated",
        "rights_status": "generated",
        "captured_at": "t",
        "parse_status": "pending",
        "role": "reference",
        "x": 0,
        "y": 0,
        "w": 0,
        "h": 0,
        "z": 0,
        "parse_attempts": 0,
        "created_at": "t",
        **kw,
    }
    cols = ", ".join(row)
    c.execute(
        text(f"INSERT INTO board_items ({cols}) VALUES ({', '.join(':' + k for k in row)})"), row
    )


def test_migration_upgrade_head(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine)
    insp = inspect(engine)
    assert {"explorations", "explore_options"} <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("board_items")}
    assert {"explore_option_id", "generation_json", "check_json"} <= cols
    assert all(
        fk["constrained_columns"] != ["explore_option_id"]
        for fk in insp.get_foreign_keys("board_items")
    )
    with engine.begin() as c:
        idx = c.execute(
            text("SELECT sql FROM sqlite_master WHERE name='uq_board_items_active_sha256'")
        ).scalar()
        assert idx and "WHERE" in idx
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        _insert(c)  # generated item, no corpus item
    with pytest.raises(IntegrityError), engine.begin() as c:
        _insert(c, id="itm_y", origin="upload", rights_status="licensed")
    engine.dispose()


def test_migration_downgrade_is_clean(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'd.sqlite'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi, _rec):  # type: ignore[no-untyped-def]
        dbapi.execute("PRAGMA foreign_keys=ON")

    run_migrations(engine)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        _insert(c)
        c.execute(
            text(
                "INSERT INTO explorations (id, board_id, item_id, key, created_at) "
                "VALUES ('exp_x', 'brd_x', 'itm_x', 'k', 't')"
            )
        )
    with Session(engine) as s:
        s.add(
            CorpusItem(
                id="cx_x",
                domain="d",
                source="t",
                source_id="1",
                landing_url="u",
                image_url="u",
                license_code="cc0",
                attribution_text="a",
            )
        )
        s.add(Lens(id="lens_x", domain="d", version=1, origin="o", spec_json={}))
        s.flush()
        s.add(
            VariationRun(
                id="run_x",
                board_id="brd_x",
                source_item_id="itm_x",
                lens_id="lens_x",
                target_key="k",
                mode="m",
                target_values_json={},
                protected_keys_json=[],
                source_snapshot_json={},
                board_profile_version=1,
                ranking_version="r",
                ranking_config_json={},
                validator_version="v",
                providers_json={},
                idempotency_key="idem",
            )
        )
        s.flush()
        s.add(RunCandidate(id="cand_x", run_id="run_x", corpus_item_id="cx_x"))
        s.flush()
        s.add(
            ValidationResult(
                run_candidate_id="cand_x",
                check="c",
                verdict="pass",
                reason="r",
                validator_version="v",
            )
        )
        s.commit()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with engine.begin() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0003")
    names = set(inspect(engine).get_table_names())
    assert "explorations" not in names and "explore_options" not in names
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM board_items")).scalar() == 0
    engine.dispose()


def test_migration_keeps_referenced_items_with_fks_on(tmp_path: Path) -> None:
    # board_items is rebuilt by 0004; rows elsewhere point at it, and the app's engine
    # runs with foreign_keys=ON, so the rebuild's DROP TABLE must not trip the FKs
    engine = create_engine(f"sqlite:///{tmp_path / 'fk.sqlite'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi, _rec):  # type: ignore[no-untyped-def]
        dbapi.execute("PRAGMA foreign_keys=ON")

    run_migrations(engine, "0003")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        _insert(c, origin="upload", rights_status="user_supplied", sha256="a" * 64)
        _insert(
            c,
            id="itm_child",
            origin="upload",
            rights_status="user_supplied",
            parent_item_id="itm_x",
        )
        c.execute(
            text(
                "INSERT INTO item_attributes (id, item_id, key, label, category, kind, "
                "confidence, status, source, source_detail, enabled, updated_at) "
                "VALUES ('att_x', 'itm_x', 'palette', 'Palette', 'colour', 'palette', "
                "0.9, 'confirmed', 'model', '', 1, 't')"
            )
        )

    def counts() -> dict[str, int]:
        with engine.connect() as c:
            return {
                t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                for t in ("boards", "board_items", "item_attributes")
            }

    before = counts()
    assert before == {"boards": 1, "board_items": 2, "item_attributes": 1}
    run_migrations(engine)
    assert counts() == before
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        parent = c.execute(
            text("SELECT parent_item_id FROM board_items WHERE id = 'itm_child'")
        ).scalar()
        assert parent == "itm_x"
        idx = c.execute(
            text("SELECT sql FROM sqlite_master WHERE name='uq_board_items_active_sha256'")
        ).scalar()
        assert idx and "WHERE" in idx
        table_sql = c.execute(
            text("SELECT sql FROM sqlite_master WHERE name='board_items'")
        ).scalar()
        assert "ck_item_licensed_iff_corpus" in table_sql
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0003")
    assert counts() == before
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        table_sql = c.execute(
            text("SELECT sql FROM sqlite_master WHERE name='board_items'")
        ).scalar()
        assert "explore_option_id" not in table_sql
        assert "ck_item_licensed_iff_corpus" in table_sql
    engine.dispose()
