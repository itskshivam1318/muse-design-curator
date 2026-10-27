from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings


@pytest.fixture(autouse=True)
def _ignore_repo_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's repo-root .env."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(autouse=True)
def _mock_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The code defaults are live; the test environment is always mock (and offline)."""
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    monkeypatch.setenv("SEGMENTATION_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDER", "mock")


@pytest.fixture(autouse=True)
def _no_live_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live source search is off unless a test turns it on (and then uses fake transports)."""
    monkeypatch.setenv("LIVE_SEARCH", "0")


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite with the schema built by running Alembic migrations."""
    from app.db.session import make_engine, run_migrations

    engine = make_engine("sqlite://", poolclass=StaticPool)
    run_migrations(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(d))
    monkeypatch.setenv("JOBS_SYNC", "1")
    return d


@pytest.fixture(autouse=True)
def _no_job_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Background jobs never reach the developer's database; `client` points them at its own."""
    from app.api import deps

    def refuse() -> None:
        raise RuntimeError("no job database in this test")

    monkeypatch.setattr(deps, "_factory", refuse)


@pytest.fixture
def client(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app import jobs
    from app.api import deps
    from app.api.deps import get_session
    from app.db.session import make_engine, make_session_factory, run_migrations
    from app.extraction import service
    from app.main import app

    engine = make_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    run_migrations(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(deps, "_factory", lambda: factory)

    def override() -> Iterator[Session]:
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    jobs.register("parse_item", service.parse_item_job)  # other tests may have cleared the registry
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
