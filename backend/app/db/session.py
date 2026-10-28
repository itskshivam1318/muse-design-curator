import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import Settings, resolve_repo_path

log = logging.getLogger(__name__)
BUSY_TIMEOUT_MS = 15000  # a writer waits this long for another connection's write lock
BACKEND_DIR = Path(__file__).resolve().parents[2]


def resolve_database_url(settings: Settings) -> str:
    """Relative sqlite file paths resolve against the repo root (single source of truth)."""
    url = make_url(settings.DATABASE_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return settings.DATABASE_URL
    return str(url.set(database=str(resolve_repo_path(url.database))))


def make_engine(url: str, **kwargs: Any) -> Engine:
    if url.startswith("sqlite") and make_url(url).database not in (None, "", ":memory:"):
        Path(str(make_url(url).database)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if engine.url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cur.close()

    return engine


def make_engine_from_settings(settings: Settings) -> Engine:
    return make_engine(resolve_database_url(settings))


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def migration_transaction(engine: Engine) -> Iterator[Connection]:
    """One transaction for a whole migration run, so each revision's schema change
    commits together with its alembic_version stamp.

    On SQLite, batch migrations rebuild tables that other rows reference, and the
    DROP of the old table fails under foreign_keys=ON. So enforcement is turned
    off before the transaction starts (the pragma is a no-op inside one), checked
    with foreign_key_check before commit, and restored before the connection goes
    back to the pool. The explicit BEGIN keeps pysqlite from autocommitting DDL.
    """
    with engine.connect() as conn:
        if engine.url.get_backend_name() != "sqlite":
            with conn.begin():
                yield conn
            return
        raw = conn.connection.driver_connection
        assert raw is not None
        was_on = bool(raw.execute("PRAGMA foreign_keys").fetchone()[0])
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            with conn.begin():
                raw.execute("BEGIN")
                yield conn
                bad = raw.execute("PRAGMA foreign_key_check").fetchall()
                if bad:
                    raise RuntimeError(f"foreign key violations after migrating: {bad[:20]}")
        finally:
            raw.execute(f"PRAGMA foreign_keys={'ON' if was_on else 'OFF'}")


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def run_migrations(engine: Engine, revision: str = "head") -> None:
    cfg = alembic_config()
    with migration_transaction(engine) as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)


_PENDING = "_after_commit_callbacks"


def after_commit(session: Session, fn: Callable[[], None]) -> None:
    """Run fn once after the current transaction commits; drop it on rollback.

    With no active transaction there is nothing to wait for, so fn runs immediately.
    """
    if not session.in_transaction():
        fn()
        return
    pending: list[Callable[[], None]] | None = session.info.get(_PENDING)
    if pending is None:
        pending = session.info[_PENDING] = []

        def _commit(sess: Session) -> None:
            callbacks = sess.info.get(_PENDING, [])
            sess.info[_PENDING] = []
            for cb in callbacks:
                try:
                    cb()
                except Exception:
                    log.exception("after_commit callback failed")

        def _rollback(sess: Session) -> None:
            sess.info[_PENDING] = []

        event.listen(session, "after_commit", _commit)
        event.listen(session, "after_rollback", _rollback)
    pending.append(fn)
