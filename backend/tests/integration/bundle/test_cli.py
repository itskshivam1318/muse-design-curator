import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.bundle import __main__ as cli
from app.db.models import Board
from app.db.session import make_engine, make_session_factory, run_migrations
from tests.integration.bundle.conftest import Built, add_vary_run

BACKEND = Path(__file__).resolve().parents[3]


def _cli(data: Path, *args: str, db: str = "dle.sqlite") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{data / db}",
        "DATA_DIR": str(data),
    }
    return subprocess.run(
        [sys.executable, "-m", "app.bundle", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.file_db
def test_export_then_import_into_another_server(
    built_board: Built, db: Session, data_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "b.zip"
    exported = _cli(data_dir, "export", built_board.id, str(out), db="test.sqlite")
    assert exported.returncode == 0, exported.stderr
    assert exported.stdout.startswith(f"exported Bundle me ({built_board.id}): ")
    assert exported.stdout.rstrip().endswith(f" files -> {out}")

    other = tmp_path / "other"
    engine = make_engine(f"sqlite:///{other / 'dle.sqlite'}")
    run_migrations(engine)
    engine.dispose()
    imported = _cli(other, "import", str(out))
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.startswith(f"imported Bundle me ({built_board.id}): ")
    assert imported.stdout.rstrip().endswith(" new files")
    assert "0 new files" not in imported.stdout

    again = _cli(other, "import", str(out))
    assert again.returncode == 1
    assert again.stderr.startswith("error BOARD_EXISTS:")

    # a visitor's Vary run on the target server is removed by --replace, and the CLI says so
    engine = make_engine(f"sqlite:///{other / 'dle.sqlite'}")
    with make_session_factory(engine)() as s:
        add_vary_run(s, built_board.id, built_board.image_a)
    engine.dispose()
    replaced = _cli(other, "import", str(out), "--replace")
    assert replaced.returncode == 0, replaced.stderr
    assert "0 new files" in replaced.stdout
    lines = replaced.stdout.splitlines()
    assert lines[1].startswith("removed from this server: ")
    assert "variation_runs 1" in lines[1]


def test_unexpected_failure_rolls_back_and_names_the_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "d"
    url = f"sqlite:///{data / 'dle.sqlite'}"
    engine = make_engine(url)
    run_migrations(engine)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATA_DIR", str(data))

    def half_import(session: Session, bundle: Path, *, replace: bool = False) -> dict[str, Any]:
        session.add(Board(id="brd_half", title="half"))
        session.flush()  # written in the transaction, then the import fails
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "import_board", half_import)
    assert cli.main(["import", str(tmp_path / "x.zip")]) == 1
    assert capsys.readouterr().err == "error RuntimeError: boom\n"
    with make_session_factory(engine)() as s:
        assert s.get(Board, "brd_half") is None
    engine.dispose()
