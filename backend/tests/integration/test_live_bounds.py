"""Concurrency and deadline guarantees of the live stage."""

import threading
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from sqlalchemy.orm import Session

from app import jobs
from app.corpus.indexer import EmbeddingStore, embeddings_path
from app.corpus.sources.base import ManifestItem, item_id
from app.db.models import CorpusItem
from app.db.session import make_engine, make_session_factory, run_migrations
from app.live import quick_index as qi
from app.providers.embedding import MockEmbedder
from tests.media import image_bytes


def mi(sid: str) -> ManifestItem:
    return ManifestItem(
        id=item_id("commons", sid), domain="watch", source="commons", source_id=sid,
        landing_url=f"https://c/{sid}", image_url=f"https://img.test/{sid}.png",
        creator_name="A", license_code="CC0-1.0", attribution_text=sid,
    )  # fmt: skip


def test_concurrent_quick_indexes_get_distinct_rows_and_correct_vectors(
    data_dir: Path, tmp_path: Path
) -> None:  # fmt: skip
    engine = make_engine(f"sqlite:///{tmp_path / 'race.sqlite'}")
    run_migrations(engine)
    factory = make_session_factory(engine)
    images = {f"{p}{n}.png": image_bytes("PNG", (300, 300), seed)
              for seed, (p, n) in enumerate((p, n) for p in "ab" for n in range(6))}  # fmt: skip
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=images[req.url.path.strip("/")])
        )
    )
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def work(prefix: str) -> None:
        try:
            with factory() as s:
                barrier.wait()
                qi.quick_index(s, [mi(f"{prefix}{n}") for n in range(6)], "watch", client=client)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(p,)) for p in "ab"]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    with factory() as s:
        rows = list(s.query(CorpusItem).all())
    assert len(rows) == 12
    assert sorted(r.embedding_row for r in rows) == list(range(12))
    matrix = EmbeddingStore(embeddings_path(), keep_rows=12).matrix
    assert matrix is not None and matrix.shape[0] == 12
    emb = MockEmbedder()
    for r in rows:
        want = emb.embed_images([images[r.image_url.split("/")[-1]]])[0]
        assert np.allclose(matrix[r.embedding_row], want, atol=1e-5), r.id
    engine.dispose()


def test_background_queue_does_not_starve_default_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBS_SYNC", "0")
    gate = threading.Event()
    started: list[int] = []
    ran = threading.Event()

    def slow(n: int) -> None:
        started.append(n)
        gate.wait(5)

    jobs.register("t_bg", slow, queue="background")
    jobs.register("t_run", lambda: ran.set())
    try:
        for n in range(16):
            jobs.enqueue("t_bg", n=n)
        jobs.enqueue("t_run")
        assert ran.wait(2), "a run job must start while 16 background jobs are queued"
        assert len(started) <= 1  # one background worker
    finally:
        gate.set()


def test_background_queue_drops_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBS_SYNC", "0")
    gate = threading.Event()
    seen: list[int] = []
    jobs.register("t_bg2", lambda n: (seen.append(n), gate.wait(5)), queue="background")
    try:
        before = jobs._pending["background"]
        for n in range(jobs.BACKGROUND_MAX_PENDING + 10):
            jobs.enqueue("t_bg2", n=n)
        assert jobs._pending["background"] - before <= jobs.BACKGROUND_MAX_PENDING
        assert jobs._pending["background"] <= jobs.BACKGROUND_MAX_PENDING
    finally:
        gate.set()
        deadline = time.monotonic() + 5
        while jobs._pending["background"] and time.monotonic() < deadline:
            time.sleep(0.05)


def test_quick_index_returns_at_the_deadline_with_partial_results(
    session: Session, data_dir: Path
) -> None:  # fmt: skip
    landed: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        n = req.url.path.strip("/")
        if n.startswith("slow"):
            time.sleep(3)
        return httpx.Response(200, content=image_bytes("PNG", (300, 300), abs(hash(n)) % 1000))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = [mi("fast1"), mi("fast2")] + [mi(f"slow{i}") for i in range(4)]
    report: dict[str, int] = {}
    t0 = time.monotonic()
    rows = qi.quick_index(
        session, items, "watch", client=client, deadline=time.monotonic() + 0.6,
        on_download=landed.append, report=report,
    )  # fmt: skip
    assert time.monotonic() - t0 < 2.5
    assert {r.id for r in rows} == {"cx_commons_fast1", "cx_commons_fast2"}
    assert report["dropped"] == 4 and landed == [1, 2]


def test_write_queries_times_out(session: Session) -> None:
    from app.providers.reasoning import MockReasoningProvider
    from tests.unit.live.test_queries import make_spec

    class Slow(MockReasoningProvider):
        def extract(self, images, schema, prompt):  # type: ignore[no-untyped-def]
            time.sleep(2)
            return super().extract(images, schema, prompt)

    from app.live import queries

    spec, lens = make_spec()
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        queries.write_queries(spec, {}, lens, "", Slow(), session=session, timeout=0.2)  # type: ignore[arg-type]
    assert time.monotonic() - t0 < 1.5
    _ = Any
