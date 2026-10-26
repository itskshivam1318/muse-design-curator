from pathlib import Path

from app.config import Settings, data_dir
from app.db.session import resolve_database_url

ROOT = Path(__file__).resolve().parents[4]


def test_relative_paths_resolve_against_repo_root() -> None:
    s = Settings(DATABASE_URL="sqlite:///./data/dle.sqlite", DATA_DIR="./data")
    assert data_dir(s) == ROOT / "data"
    assert resolve_database_url(s) == f"sqlite:///{ROOT / 'data' / 'dle.sqlite'}"


def test_absolute_and_memory_urls_untouched(tmp_path: Path) -> None:
    s = Settings(DATABASE_URL=f"sqlite:///{tmp_path}/x.sqlite", DATA_DIR=str(tmp_path))
    assert data_dir(s) == tmp_path
    assert resolve_database_url(s) == f"sqlite:///{tmp_path}/x.sqlite"
    assert resolve_database_url(Settings(DATABASE_URL="sqlite://")) == "sqlite://"
    assert resolve_database_url(Settings(DATABASE_URL="postgresql://h/db")) == "postgresql://h/db"
