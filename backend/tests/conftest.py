import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _ignore_repo_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's repo-root .env."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
