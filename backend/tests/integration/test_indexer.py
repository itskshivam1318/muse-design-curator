import importlib.util
import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import jobs
from app.corpus import hashing
from app.corpus.indexer import embeddings_path, index_corpus
from app.db.models import Board, BoardItem, CorpusAttribute, CorpusItem

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
MANIFEST = FIXTURES / "manifest.jsonl"
SEED_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"
DOMAINS = ("watch", "fashion", "interior", "ui")


def counts(session: Session) -> tuple[int, int]:
    return (
        session.scalar(select(func.count()).select_from(CorpusItem)) or 0,
        session.scalar(select(func.count()).select_from(CorpusAttribute)) or 0,
    )


def by_source_id(session: Session) -> dict[str, CorpusItem]:
    return {c.source_id: c for c in session.scalars(select(CorpusItem))}


@pytest.fixture
def indexed(session: Session, data_dir: Path) -> Session:
    for d in DOMAINS:
        index_corpus(session, d, MANIFEST)
    return session


def test_fixture_corpus_indexes_with_mock_providers_quickly(
    session: Session, data_dir: Path
) -> None:
    started = time.perf_counter()
    reports = [index_corpus(session, d, MANIFEST) for d in DOMAINS]
    assert time.perf_counter() - started < 10
    rows = by_source_id(session)
    assert len(rows) == 37
    assert sum(r.indexed for r in reports) == 34  # 32 + byte-identical + resized copies
    assert sum(r.invalid for r in reports) == 2
    assert sum(r.failed for r in reports) == 1

    ok = rows["watch_03"]
    assert (ok.indexing_status, ok.provenance_status) == ("indexed", "valid")
    assert ok.sha256 and ok.dhash and len(ok.dhash) == 16 and (ok.width, ok.height) == (256, 256)
    assert ok.local_path and (data_dir / ok.local_path).is_file()
    assert session.scalars(select(CorpusAttribute).where(CorpusAttribute.item_id == ok.id)).first()

    # no rights, no processing: pending + invalid, never fetched, no embedding, no attributes
    for sid, issue in (
        ("watch_reserved", "LICENSE_NOT_ALLOWED"),
        ("watch_by_nocreator", "MISSING_CREATOR"),
    ):
        r = rows[sid]
        assert (r.indexing_status, r.provenance_status, r.provenance_issue) == (
            "pending", "invalid", issue,
        )  # fmt: skip
        assert r.embedding_row is None and r.sha256 is None and r.local_path is None
        assert not session.scalars(
            select(CorpusAttribute).where(CorpusAttribute.item_id == r.id)
        ).first()

    # duplicates are not dropped at index time: retrieval decides at query time
    orig, dup, small = rows["watch_01"], rows["watch_dup"], rows["watch_02_small"]
    for r in (orig, dup, small, rows["watch_02"]):
        assert r.indexing_status == "indexed" and r.embedding_row is not None and r.dhash
    assert dup.sha256 == orig.sha256 and dup.embedding_row != orig.embedding_row
    assert hashing.hamming(small.dhash or "", rows["watch_02"].dhash or "") <= 6

    missing = rows["watch_missing"]
    assert (missing.indexing_status, missing.provenance_status) == ("failed", "valid")


def test_embeddings_are_normalised_float32_one_row_per_indexed_item(indexed: Session) -> None:
    m = np.load(embeddings_path(), allow_pickle=False)
    rows = [
        c.embedding_row for c in indexed.scalars(select(CorpusItem)) if c.embedding_row is not None
    ]
    assert m.dtype == np.float32 and m.shape[0] == len(rows) == 34
    assert sorted(rows) == list(range(34))
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-5)
    assert not list(embeddings_path().parent.glob("*.tmp"))


def test_indexer_is_idempotent(session: Session, data_dir: Path) -> None:
    for d in DOMAINS:
        index_corpus(session, d, MANIFEST)
    before = counts(session)
    matrix = np.load(embeddings_path())
    second = [index_corpus(session, d, MANIFEST) for d in DOMAINS]
    assert counts(session) == before
    assert np.array_equal(np.load(embeddings_path()), matrix)
    assert sum(r.skipped for r in second) == 34
    assert sum(r.indexed for r in second) == 0


def test_missing_image_marks_failed(indexed: Session) -> None:
    row = by_source_id(indexed)["watch_missing"]
    assert row.indexing_status == "failed" and row.provenance_status == "valid"
    assert row.embedding_row is None and row.sha256 is None


def test_embedding_rows_survive_a_second_manifest(
    session: Session, data_dir: Path, tmp_path: Path
) -> None:
    index_corpus(session, "ui", MANIFEST)
    first = {c.id: c.embedding_row for c in session.scalars(select(CorpusItem))}
    index_corpus(session, "fashion", MANIFEST)
    after = {c.id: c.embedding_row for c in session.scalars(select(CorpusItem))}
    assert all(after[k] == v for k, v in first.items())
    assert np.load(embeddings_path()).shape[0] == 16


def test_interrupted_run_leaves_a_readable_file(session: Session, data_dir: Path) -> None:
    index_corpus(session, "ui", MANIFEST)
    matrix = np.load(embeddings_path())
    # an interrupted run wrote rows the database never kept: they are dropped, not reused as ghosts
    np.save(embeddings_path(), np.vstack([matrix, matrix[:3]]))
    index_corpus(session, "fashion", MANIFEST)
    assert np.load(embeddings_path()).shape[0] == 16
    rows = sorted(r for r in session.scalars(select(CorpusItem.embedding_row)) if r is not None)
    assert rows == list(range(16))


def test_changed_license_in_manifest_updates_provenance(
    session: Session, data_dir: Path, tmp_path: Path
) -> None:
    shutil.copytree(FIXTURES, tmp_path / "c")
    man = tmp_path / "c" / "manifest.jsonl"
    index_corpus(session, "ui", man)
    erow = by_source_id(session)["ui_01"].embedding_row
    assert erow is not None
    rows = [json.loads(ln) for ln in man.read_text().splitlines()]
    for r in rows:
        if r["source_id"] == "ui_01":
            r["license_code"] = "CC-BY-NC-4.0"
    man.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    index_corpus(session, "ui", man)
    row = by_source_id(session)["ui_01"]
    assert (row.provenance_status, row.provenance_issue) == ("invalid", "LICENSE_NOT_ALLOWED")
    assert row.indexing_status == "indexed" and row.embedding_row == erow  # row kept, just excluded


def test_failed_item_that_becomes_invalid_is_pending(
    session: Session, data_dir: Path, tmp_path: Path
) -> None:
    shutil.copytree(FIXTURES, tmp_path / "c")
    man = tmp_path / "c" / "manifest.jsonl"
    index_corpus(session, "watch", man)
    assert by_source_id(session)["watch_missing"].indexing_status == "failed"
    rows = [json.loads(ln) for ln in man.read_text().splitlines()]
    for r in rows:
        if r["source_id"] == "watch_missing":
            r["license_code"] = "All rights reserved"
    man.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    index_corpus(session, "watch", man)
    row = by_source_id(session)["watch_missing"]
    assert (row.indexing_status, row.provenance_status) == ("pending", "invalid")


def _seed_module() -> Any:
    spec = importlib.util.spec_from_file_location("seed_script", SEED_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_creates_four_boards_with_licensed_items(
    indexed: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    queued: list[str] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append(kw["item_id"]))
    seed = _seed_module()
    seed.seed(indexed)
    indexed.commit()
    boards = list(indexed.scalars(select(Board)))
    assert {b.domain for b in boards} == set(DOMAINS) and len(boards) == 4
    valid_ids = set(
        indexed.scalars(select(CorpusItem.id).where(CorpusItem.provenance_status == "valid"))
    )
    for b in boards:
        assert b.title and b.context
        items = list(indexed.scalars(select(BoardItem).where(BoardItem.board_id == b.id)))
        assert 3 <= len(items) <= 8
        in_domain = list(
            indexed.scalars(
                select(CorpusItem).where(
                    CorpusItem.domain == b.domain, CorpusItem.indexing_status == "indexed",
                    CorpusItem.provenance_status == "valid",
                )
            )
        )  # fmt: skip
        on_board = {i.corpus_item_id for i in items}
        assert len([c for c in in_domain if c.id not in on_board]) >= len(items)  # pool left
        for it in items:
            assert (it.origin, it.rights_status) == ("seed", "licensed")
            assert it.corpus_item_id in valid_ids and it.storage_path and it.thumb_path
        assert len({(i.x, i.y) for i in items}) == len(items)  # laid out, not stacked
    assert len(queued) == sum(1 for _ in indexed.scalars(select(BoardItem)))
    seed.seed(indexed)  # re-running adds nothing
    indexed.commit()
    assert indexed.scalar(select(func.count()).select_from(Board)) == 4
