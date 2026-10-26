import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.session import make_engine, make_session_factory, resolve_database_url, run_migrations

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _factory() -> sessionmaker[Session]:
    engine = make_engine(
        resolve_database_url(get_settings()), connect_args={"check_same_thread": False}
    )
    run_migrations(engine)
    return make_session_factory(engine)


def get_session() -> Iterator[Session]:
    """One session per request; commit on success, roll back on error."""
    with _lock:
        factory = _factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
