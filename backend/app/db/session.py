import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import Settings, resolve_repo_path

log = logging.getLogger(__name__)
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
            cur.close()

    return engine


def make_engine_from_settings(settings: Settings) -> Engine:
    return make_engine(resolve_database_url(settings))


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def run_migrations(engine: Engine, revision: str = "head") -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with engine.begin() as conn:
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
