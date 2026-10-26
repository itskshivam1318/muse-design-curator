from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings


@pytest.fixture(autouse=True)
def _ignore_repo_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's repo-root .env."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite with the schema built by running Alembic migrations."""
    from app.db.session import make_engine, run_migrations

    engine = make_engine("sqlite://", poolclass=StaticPool)
    run_migrations(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()
