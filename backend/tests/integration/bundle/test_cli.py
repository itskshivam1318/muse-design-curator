import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.bundle import __main__ as cli
from app.db.models import Board, BoardItem
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
    lines = exported.stdout.splitlines()
    # the first line names the database and DATA_DIR it used, so a wrong server shows at once
    assert lines[0] == f"database sqlite:///{data_dir / 'test.sqlite'}, files {data_dir}"
    assert lines[1].startswith(f"exported Bundle me ({built_board.id}): ")
    assert lines[1].endswith(f" files -> {out}")
    # the chained item was never read: the server that imports it reads it again
    assert lines[2:] == [
        "note: 1 items are not finished and will be read again on the server (model calls)"
    ]

    other = tmp_path / "other"
    engine = make_engine(f"sqlite:///{other / 'dle.sqlite'}")
    run_migrations(engine)
    engine.dispose()
    imported = _cli(other, "import", str(out))
    assert imported.returncode == 0, imported.stderr
    lines = imported.stdout.splitlines()
    assert lines[0] == f"database sqlite:///{other / 'dle.sqlite'}, files {other}"
    assert lines[1].startswith(f"imported Bundle me ({built_board.id}): ")
    assert lines[1].endswith(" new files")
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
    assert lines[2].startswith("removed from this server: ")
    assert "variation_runs 1" in lines[2]


@pytest.mark.file_db
def test_export_says_nothing_of_unfinished_items_when_all_are_read(
    built_board: Built, db: Session, data_dir: Path, tmp_path: Path
) -> None:
    db.execute(update(BoardItem).values(parse_status="completed"))
    db.commit()
    exported = _cli(data_dir, "export", built_board.id, str(tmp_path / "b.zip"), db="test.sqlite")
    assert exported.returncode == 0, exported.stderr
    assert "note:" not in exported.stdout
    assert len(exported.stdout.splitlines()) == 2


@pytest.mark.file_db
def test_import_into_an_unmigrated_database_refuses(
    built_board: Built, db: Session, data_dir: Path, tmp_path: Path
) -> None:
    out = tmp_path / "b.zip"
    assert _cli(data_dir, "export", built_board.id, str(out), db="test.sqlite").returncode == 0
    empty = tmp_path / "empty"  # a database nobody migrated, as a stray image database would be
    imported = _cli(empty, "import", str(out))
    assert imported.returncode == 1
    assert imported.stdout.splitlines() == [
        f"database sqlite:///{empty / 'dle.sqlite'}, files {empty}"
    ]
    assert imported.stderr.startswith("error DB_NOT_MIGRATED:")
    assert not [p for p in empty.rglob("*") if p.is_file() and not p.name.startswith("dle.sqlite")]


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
