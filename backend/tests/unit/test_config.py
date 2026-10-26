from pathlib import Path

from app.config import ENV_FILE, Settings


def test_env_file_is_repo_root() -> None:
    assert ENV_FILE == Path(__file__).resolve().parents[3] / ".env"


def test_settings_reads_env_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    f = tmp_path / ".env"
    f.write_text("MODEL_API_KEY=from-file\nMODEL_MAX_RETRIES=5\n")
    s = Settings(_env_file=f)  # type: ignore[call-arg]
    assert s.MODEL_API_KEY == "from-file"
    assert s.MODEL_MAX_RETRIES == 5


def test_env_var_overrides_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / ".env"
    f.write_text("MODEL_API_KEY=from-file\n")
    monkeypatch.setenv("MODEL_API_KEY", "from-env")
    assert Settings(_env_file=f).MODEL_API_KEY == "from-env"  # type: ignore[call-arg]
