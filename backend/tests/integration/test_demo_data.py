"""demo_data driver and indexer knobs: caps are enforced, nothing live runs without --yes."""

import importlib.util
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from app.corpus import indexer

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
FIXTURE_MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "corpus" / "manifest.jsonl"


@pytest.fixture
def demo_data(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("demo_data", SCRIPTS / "demo_data.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_batch_is_five_and_http_timeout_is_hard() -> None:
    assert indexer.BATCH_SIZE == 5
    t = indexer.HTTP_TIMEOUT
    assert (t.connect, t.read, t.write, t.pool) == (10.0, 15.0, 15.0, 15.0)
    assert isinstance(t, httpx.Timeout)


def test_indexer_commits_every_batch(session: Session, data_dir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commits: list[int] = []
    real = session.commit
    monkeypatch.setattr(session, "commit", lambda: (commits.append(1), real())[1])
    report = indexer.index_corpus(session, "watch", FIXTURE_MANIFEST, batch_size=2)
    processed = report.indexed + report.failed
    assert processed >= 4
    assert len(commits) == processed // 2 + 1  # one per 2 items, plus the final checkpoint


def test_client_uses_the_hard_timeout(session: Session, data_dir: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[Any] = []
    real = httpx.Client

    def spy(*a: Any, **kw: Any) -> httpx.Client:
        seen.append(kw.get("timeout"))
        return real(*a, **kw)

    monkeypatch.setattr(indexer.httpx, "Client", spy)
    indexer.index_corpus(session, "ui", FIXTURE_MANIFEST, limit=1)
    assert seen == [indexer.HTTP_TIMEOUT]


def test_without_yes_nothing_runs(demo_data: Any, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    import index_corpus
    import seed

    def boom(*_a: Any, **_k: Any) -> int:
        raise AssertionError("must not run")

    monkeypatch.setattr(index_corpus, "main", boom)
    monkeypatch.setattr(seed, "main", boom)
    monkeypatch.setattr(demo_data, "run_imports", boom)
    assert demo_data.main([]) == 0
    assert "add --yes" in capsys.readouterr().out


def test_yes_indexes_with_limits_then_seeds_without_indexing(demo_data: Any, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import index_corpus
    import seed

    index_calls: list[list[str]] = []
    seed_calls: list[list[str]] = []
    monkeypatch.setattr(index_corpus, "main", lambda argv: index_calls.append(argv) or 0)
    monkeypatch.setattr(seed, "main", lambda argv: seed_calls.append(argv) or 0)
    assert demo_data.main(["--yes", "--skip-import"]) == 0
    assert [(c[1], c[3]) for c in index_calls] == [
        (d, str(demo_data.INDEX_LIMIT[d])) for d in demo_data.DOMAINS
    ]
    assert seed_calls == [["--no-index"]]
