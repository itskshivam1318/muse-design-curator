"""Hybrid retrieval: live licensed-source search merged with the indexed corpus (all offline)."""

import io
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select

from app import events, jobs
from app.corpus.sources.base import ManifestItem, item_id
from app.db.models import CorpusAttribute, CorpusItem, VariationRun
from app.db.repos import runs as runs_repo
from app.live import quick_index as qi
from app.retrieval.pool import Pool
from app.runs import orchestrator
from tests.integration.runs.test_orchestrator import make_run


PALETTE = [
    (200, 30, 30),
    (30, 60, 200),
    (30, 160, 60),
    (240, 240, 240),
    (20, 20, 20),
    (240, 140, 20),
]


def colour_image(n: int) -> bytes:
    """A block mosaic whose dominant colour cycles through distinct hues (distinct dHashes)."""
    rng = np.random.default_rng(n)
    base = np.array(PALETTE[n % len(PALETTE)], dtype=np.uint8)
    cells = np.where(rng.random((9, 9, 1)) < 0.75, base, rng.integers(0, 255, (9, 9, 3)))
    arr = np.kron(cells.astype(np.uint8), np.ones((40, 40, 1), dtype=np.uint8))
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def mi(source: str, n: int) -> ManifestItem:
    return ManifestItem(
        id=item_id(source, str(n)), domain="watch", source=source, source_id=str(n),
        landing_url=f"https://{source}.test/{n}", image_url=f"https://img.test/{source}/{n}.png",
        creator_name="A. Maker", license_code="CC0-1.0", attribution_text=f"credit {source} {n}",
    )  # fmt: skip


class FakeSource:
    def __init__(self, name: str, items: list[ManifestItem], error: Exception | None = None):
        self.name, self.items, self.error = name, items, error
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        self.queries.append(query)
        if self.error:
            raise self.error
        yield from self.items[:limit]


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Live search on, with fake source adapters and an in-memory image downloader."""
    monkeypatch.setenv("LIVE_SEARCH", "1")
    monkeypatch.setenv("LIVE_SOURCES", "commons,openverse")
    monkeypatch.setenv("LIVE_TIMEOUT_S", "5")
    env: dict[str, Any] = {"downloads": [], "sources": {}}
    seeds = iter(range(100, 10_000))
    images: dict[str, bytes] = {}

    def download(_client: Any, url: str, _limit: int) -> bytes:
        env["downloads"].append(url)
        if url not in images:
            images[url] = colour_image(next(seeds))
        return images[url]

    monkeypatch.setattr(qi, "_download", download)
    monkeypatch.setattr("app.live.search.make_source", lambda name, _d: env["sources"][name])
    return env


def two_sources(live: dict[str, Any], n: int = 4, **kw: Any) -> None:
    live["sources"]["commons"] = FakeSource("commons", [mi("commons", i) for i in range(n)])
    live["sources"]["openverse"] = FakeSource(
        "openverse", [mi("openverse", i) for i in range(n)], **kw
    )  # fmt: skip


def origins(world: dict[str, Any], run: VariationRun) -> dict[str, str]:
    world["session"].expire_all()
    return {
        c.corpus_item_id: c.origin or "corpus"
        for c in runs_repo.candidates(world["session"], run.id)
    }


def test_empty_corpus_still_returns_live_candidates_through_validation(
    world, live, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)
    monkeypatch.setattr(orchestrator, "build_pool", lambda *a, **k: Pool())
    run = make_run(world, world["watch"])
    assert run.status == "completed", run.error_code
    rows = runs_repo.candidates(world["session"], run.id)
    assert rows and all(c.origin == "live" for c in rows)
    checked = [c for c in rows if c.state in ("validated", "uncertain", "rejected")]
    assert checked, "live candidates must go through the validator"
    assert all(runs_repo.validations(world["session"], c.id) for c in checked)
    assert any(c.rank is not None for c in rows)
    live_block = run.summary_json["live"]
    assert live_block["found"] == 8 and live_block["sources"] == {
        "commons": "ok",
        "openverse": "ok",
    }
    assert live_block["kept"] == run.summary_json["returned"] > 0
    assert 3 <= len(live_block["queries"]) <= 5


def test_live_and_corpus_candidates_rank_together(world, live) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)
    run = make_run(world, world["watch"])
    assert run.status == "completed", run.error_code
    by = origins(world, run)
    assert {"live", "corpus"} <= set(by.values())
    rows = [c for c in runs_repo.candidates(world["session"], run.id) if c.state != "excluded"]
    assert {by[c.corpus_item_id] for c in rows} == {"live", "corpus"}
    assert all(c.scores_json and "total" in c.scores_json for c in rows)  # same scoring path
    ranked = sorted((c for c in rows if c.rank is not None), key=lambda c: c.rank)
    assert [c.rank for c in ranked] == list(range(1, len(ranked) + 1))
    assert all(c.state == "validated" for c in ranked)


def test_unknown_attributes_on_quick_items_never_match(world, live) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)
    run = make_run(world, world["watch"], protected_keys=["case_shape"])
    assert run.status == "completed", run.error_code
    s = world["session"]
    for c in runs_repo.candidates(s, run.id):
        if c.origin == "live" and c.state in ("validated", "uncertain", "rejected"):
            # an unread attribute never passes by itself: only measurement or a visual check can
            checks = [v for v in runs_repo.validations(s, c.id) if v.check == "protected"]
            assert checks
            for v in checks:
                if v.verdict == "pass":
                    assert v.evidence_json.get("source") in ("measured", "verify")
                else:
                    assert v.verdict in ("uncertain", "fail")


def test_failing_source_appears_in_progress_and_summary(world, live) -> None:  # type: ignore[no-untyped-def]
    import httpx

    req = httpx.Request("GET", "https://x")
    err = httpx.HTTPStatusError("x", request=req, response=httpx.Response(503, request=req))
    two_sources(live, error=err)
    with events.subscribe(world["watch"]) as sub:
        run = make_run(world, world["watch"], protected_keys=["strap_color"])
        got = []
        while (ev := sub.get(timeout=0.2)) is not None:
            if ev["type"] == "run.progress":
                got.append(ev["data"])
    assert run.status == "completed", run.error_code
    summ = run.summary_json
    assert summ["live"]["sources"] == {"commons": "ok", "openverse": "failed"}
    assert summ["live"]["failed"] == [{"source": "openverse", "error_code": "HTTP_503"}]
    assert summ["returned"] < 6
    assert "Openverse didn't respond" in [r["message"] for r in summ["shortfall"]]
    searching = [d for d in got if d["stage"] == "searching"]
    assert searching[0]["live"]["searching"] == ["commons", "openverse"]
    assert searching[-1]["live"]["sources"]["openverse"] == "failed"
    assert searching[-1]["live"]["found"] == 4
    stages = [d["stage"] for d in got]
    assert stages[0] == "searching" and stages[-1] == "completed" and "validating" in stages


def test_live_search_off_keeps_the_old_behaviour(world, live, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LIVE_SEARCH", "0")
    two_sources(live)
    with events.subscribe(world["watch"]) as sub:
        run = make_run(world, world["watch"])
        stages = []
        while (ev := sub.get(timeout=0.2)) is not None:
            if ev["type"] == "run.progress":
                stages.append(ev["data"]["stage"])
    assert run.status == "completed"
    assert stages[0] == "retrieving" and "searching" not in stages
    assert "live" not in run.summary_json and "live" not in run.progress_json
    assert live["sources"]["commons"].queries == [] and live["downloads"] == []
    assert set(origins(world, run).values()) == {"corpus"}


def test_live_items_persist_and_a_second_run_finds_them_in_the_corpus(world, live) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)
    first = make_run(world, world["watch"])
    assert first.status == "completed", first.error_code
    s = world["session"]
    s.expire_all()
    live_ids = {cid for cid, o in origins(world, first).items() if o == "live"}
    assert live_ids
    stored = {
        r.id: r
        for r in s.scalars(
            select(CorpusItem).where(CorpusItem.source.in_(["commons", "openverse"]))
        )
    }
    assert live_ids <= set(stored)
    assert all(
        r.indexing_status == "indexed" and r.index_depth in ("quick", "full")
        for r in stored.values()
    )
    downloads_before = len(live["downloads"])

    second = make_run(world, world["watch"])
    assert second.status == "completed", second.error_code
    assert len(live["downloads"]) == downloads_before  # nothing was fetched or indexed again
    assert second.summary_json["live"]["found"] == 0
    again = origins(world, second)
    assert live_ids <= set(again)
    assert all(again[i] == "corpus" for i in live_ids)  # now served from the corpus
    assert (
        s.scalar(select(func.count()).select_from(CorpusItem).where(CorpusItem.source == "commons"))
        == 4
    )


def test_shortlisted_live_items_are_deepened_to_full(world, live) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)
    run = make_run(world, world["watch"])
    assert run.status == "completed", run.error_code
    s = world["session"]
    s.expire_all()
    shortlisted = [
        c.corpus_item_id for c in runs_repo.candidates(s, run.id)
        if c.origin == "live" and c.state in ("validated", "uncertain", "rejected")
    ]  # fmt: skip
    assert shortlisted
    for cid in shortlisted:
        row = s.get(CorpusItem, cid)
        assert row.index_depth == "full"  # JOBS_SYNC ran the deepen job
        assert (
            s.scalar(
                select(func.count())
                .select_from(CorpusAttribute)
                .where(CorpusAttribute.item_id == cid)
            )
            > 0
        )


def test_at_most_sixteen_deepen_jobs_per_run(world, live, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LIVE_PER_SOURCE_LIMIT", "25")
    two_sources(live, n=25)
    queued: list[str] = []
    real = jobs.enqueue

    def spy(name: str, **kw: Any) -> None:
        if name == "deepen_item":
            queued.append(kw["corpus_item_id"])
            return
        real(name, **kw)

    monkeypatch.setattr(jobs, "enqueue", spy)
    run = make_run(world, world["watch"])
    assert run.status == "completed", run.error_code
    assert 0 < len(queued) <= 16 and len(set(queued)) == len(queued)
    assert run.progress_json["live"]["found"] == 40


def test_a_crashing_live_phase_never_fails_the_run(world, live, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("index down")

    monkeypatch.setattr(orchestrator, "quick_index", boom)
    run = make_run(world, world["watch"])
    assert run.status == "completed", run.error_code
    assert run.summary_json["live"]["found"] == 0
    assert set(origins(world, run).values()) == {"corpus"}


def test_run_api_exposes_candidate_origin(world, live, client) -> None:  # type: ignore[no-untyped-def]
    two_sources(live)
    run = make_run(world, world["watch"])
    body = client.get(f"/api/runs/{run.id}").json()
    seen = {c["origin"] for c in body["results"] + body["needs_review"] + body["rejected"]}
    assert seen <= {"corpus", "live"} and "live" in seen
    assert all("source" in c for c in body["results"])
    assert "live" in body["summary"]
