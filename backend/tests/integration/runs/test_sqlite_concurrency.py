"""A run and a background deepen job share one file-backed SQLite database (WAL) without failing."""

import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import jobs
from app.api import deps
from app.corpus.indexer import index_corpus
from app.db.models import BoardItem, CorpusItem, PartMask, VariationRun
from app.db.repos import items as items_repo
from app.db.session import make_engine, make_session_factory, run_migrations
from app.domain.variation import VariationRequest
from app.extraction import service
from app.live import quick_index as qi
from app.runs import orchestrator
from scripts import seed as seed_script
from tests.integration.runs.test_orchestrator import source_with

MANIFEST = Path(__file__).resolve().parents[2] / "fixtures" / "corpus" / "manifest.jsonl"
HOLD_S = 7.0  # longer than sqlite3's default 5 s busy timeout


def write_lock_free(path: Path) -> bool:
    """True when no other connection holds the database write lock right now."""
    con = sqlite3.connect(path, timeout=0)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


@pytest.fixture
def file_world(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    engine = make_engine(
        f"sqlite:///{tmp_path / 'dle.sqlite'}", connect_args={"check_same_thread": False}
    )
    run_migrations(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(deps, "_factory", lambda: factory)
    jobs.register("parse_item", service.parse_item_job)
    session: Session = factory()
    index_corpus(session, "watch", MANIFEST)
    session.commit()
    spec = next(b for b in seed_script.BOARDS if b["domain"] == "watch")
    board = seed_script.seed_board(session, spec, limit=8)
    session.commit()
    world = {
        "session": session, "factory": factory, "watch": board.id, "path": tmp_path / "dle.sqlite",
        "items": {board.id: [i.id for i in items_repo.list_active(session, board.id)]},
    }  # fmt: skip
    yield world
    session.close()
    engine.dispose()


def test_run_completes_while_a_deepen_job_writes_masks(
    file_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s: Session = file_world["session"]
    board = file_world["watch"]
    source_id = source_with(file_world, board, "dial_color")

    # a corpus item behind a board item (excluded from the shortlist), turned back into a quick
    # item with no cached masks, so deepening it runs SAM and writes mask rows
    other = next(i for i in file_world["items"][board] if i != source_id)
    corpus_id = s.get(BoardItem, other).corpus_item_id  # type: ignore[union-attr]
    row = s.get(CorpusItem, corpus_id)
    assert row is not None and row.sha256
    row.index_depth = "quick"
    s.execute(delete(PartMask).where(PartMask.image_sha256 == row.sha256))
    s.commit()

    # the run is created now and executed by hand below
    queued: list[str] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append(name))
    req = VariationRequest(source_item_id=source_id, target_key="dial_color", mode="explore")
    run_id = orchestrator.create_run(s, board, req, None).id
    s.commit()

    # the deepen job's second SAM call is slow, as a real one can be
    holding = threading.Event()
    lock_free: list[bool] = []
    real_seg = service.get_segmentation

    class SlowSeg:
        def __init__(self, inner: Any) -> None:
            self.inner, self.id, self.calls = inner, inner.id, 0

        def localize(self, image: bytes, sha: str, noun: str) -> Any:
            self.calls += 1
            if self.calls == 2:
                lock_free.append(write_lock_free(file_world["path"]))
                holding.set()
                time.sleep(HOLD_S)
            return self.inner.localize(image, sha, noun)

    monkeypatch.setattr(service, "get_segmentation", lambda st: SlowSeg(real_seg(st)))
    caplog.set_level(logging.WARNING)
    deepen = threading.Thread(target=qi.deepen_item, args=(corpus_id,))
    deepen.start()
    try:
        assert holding.wait(30), "the deepen job never reached its second SAM call"
        orchestrator.execute_run(file_world["factory"], run_id)
    finally:
        deepen.join(60)
    s.expire_all()
    run = s.get(VariationRun, run_id)
    assert run is not None
    assert run.status == "completed", (run.error_code, caplog.text[-800:])
    assert s.get(CorpusItem, corpus_id).index_depth == "full"  # type: ignore[union-attr]
    assert "database is locked" not in caplog.text
    assert lock_free == [True]  # the deepen job held no write transaction across its SAM call


def test_a_failed_progress_write_never_fails_the_run(
    file_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s: Session = file_world["session"]
    board = file_world["watch"]
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: None)
    req = VariationRequest(
        source_item_id=source_with(file_world, board, "dial_color"), target_key="dial_color",
        mode="explore",
    )  # fmt: skip
    run_id = orchestrator.create_run(s, board, req, None).id
    s.commit()
    real = orchestrator._progress
    skipped: list[str] = []

    def flaky(session: Session, run: VariationRun, stage: str, **extra: Any) -> None:
        real(session, run, stage, **extra)
        if stage == "retrieving" or (stage == "validating" and "shortlist_n" not in extra):
            skipped.append(stage)
            raise OperationalError("UPDATE variation_runs", {}, sqlite3.OperationalError("locked"))

    monkeypatch.setattr(orchestrator, "_progress", flaky)
    caplog.set_level(logging.WARNING)
    orchestrator.execute_run(file_world["factory"], run_id)
    s.expire_all()
    run = s.get(VariationRun, run_id)
    assert run is not None and run.status == "completed", run.error_code
    assert "retrieving" in skipped and "validating" in skipped
    assert "progress update skipped" in caplog.text


def test_busy_timeout_is_set_on_every_connection(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'x.sqlite'}")
    with engine.connect() as a, engine.connect() as b:
        for con in (a, b):
            assert con.exec_driver_sql("PRAGMA busy_timeout").scalar() == 15000
            assert con.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert con.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_a_mask_cached_by_another_connection_meanwhile_is_updated_not_duplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.repos import masks as masks_repo

    engine = make_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine)
    with Session(engine) as mine, Session(engine) as other:
        real_get = Session.get
        calls = {"n": 0}

        def stale_first(self: Session, *a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if self is mine and calls["n"] == 1:
                # the other connection caches the same mask between our read and our insert
                masks_repo.save(other, "sha", "watch case", found=False, provider="x")
                other.commit()
                return None
            return real_get(self, *a, **k)

        monkeypatch.setattr(Session, "get", stale_first)
        row = masks_repo.save(mine, "sha", "watch case", found=True, provider="y",
                              mask_path="masks/a.png", bbox_json=[0, 0, 1, 1])  # fmt: skip
        mine.commit()
        assert row.found is True and row.provider == "y"
    with Session(engine) as check:
        assert check.query(PartMask).count() == 1
        assert check.get(PartMask, ("sha", "watch case")).found is True  # type: ignore[union-attr]
    engine.dispose()
