import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from app.corpus.sources.base import ManifestItem, item_id
from app.db.repos import corpus as corpus_repo
from app.live import search


def mi(
    source: str, sid: str, *, lic: str = "CC0-1.0", creator: str | None = "A",
    url: str | None = None,
) -> ManifestItem:  # fmt: skip
    return ManifestItem(
        id=item_id(source, sid), domain="watch", source=source, source_id=sid,
        landing_url=url or f"https://x/{source}/{sid}",
        image_url=f"https://img/{source}/{sid}.jpg", creator_name=creator, license_code=lic,
        attribution_text=f"{source} {sid}",
    )  # fmt: skip


class Fake:
    def __init__(
        self, name: str, rows: dict[str, list[ManifestItem]] | None = None,
        error: Exception | None = None, delay: float = 0.0, per_item: float = 0.0,
    ) -> None:  # fmt: skip
        self.name, self.rows, self.error = name, rows or {}, error
        self.delay, self.per_item = delay, per_item
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        self.calls.append((query, limit))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        for i, it in enumerate(self.rows.get(query, self.rows.get("*", []))):
            if i >= limit:
                return
            if self.per_item:
                time.sleep(self.per_item)
            yield it


def run(fakes: dict[str, Fake], queries: list[str] | None = None, **kw: Any):  # type: ignore[no-untyped-def]
    names = list(fakes)
    return search.search_live(
        queries or ["q1", "q2"], "watch", names, kw.pop("limits", 15), kw.pop("timeout", 5.0),
        source_factory=lambda name, domain: fakes[name], **kw,
    )  # fmt: skip


def test_fans_out_sources_times_queries_concurrently() -> None:
    threads: set[str] = set()

    class Slow(Fake):
        def search(self, query, limit):  # type: ignore[no-untyped-def]
            threads.add(threading.current_thread().name)
            time.sleep(0.2)
            return super().search(query, limit)

    fakes = {
        "commons": Slow("commons", {"*": [mi("commons", "1")]}),
        "met": Slow("met", {"*": [mi("met", "2")]}),
    }
    t0 = time.monotonic()
    out = run(fakes)
    assert time.monotonic() - t0 < 0.7  # 4 tasks of 0.2s ran in parallel
    assert len(threads) >= 2
    assert {i.id for i in out} == {"cx_commons_1", "cx_met_2"}  # de-duplicated across queries
    assert all(len(f.calls) == 2 for f in fakes.values())
    assert out.sources["commons"].status == "ok" and out.sources["commons"].found == 1


def test_failing_source_is_skipped_and_recorded() -> None:
    fakes = {
        "commons": Fake("commons", {"*": [mi("commons", "1")]}),
        "openverse": Fake("openverse", error=RuntimeError("boom")),
    }
    out = run(fakes)
    assert [i.id for i in out] == ["cx_commons_1"]
    st = out.sources["openverse"]
    assert st.status == "failed" and st.error_code == "RuntimeError"
    assert out.sources["commons"].status == "ok"
    assert out.failed() == [{"source": "openverse", "error_code": "RuntimeError"}]


def test_http_error_code_is_status() -> None:
    import httpx

    req = httpx.Request("GET", "https://x")
    err = httpx.HTTPStatusError("x", request=req, response=httpx.Response(503, request=req))
    out = run({"met": Fake("met", error=err)})
    assert out.sources["met"].error_code == "HTTP_503"


def test_dedupes_against_corpus_by_id_and_landing_url(session) -> None:  # type: ignore[no-untyped-def]
    def row(sid: str, source: str, url: str, status: str) -> None:
        corpus_repo.create(
            session, id=f"cx_{source}_{sid}", domain="watch", source=source, source_id=sid,
            landing_url=url, image_url="u", license_code="CC0-1.0", attribution_text="a",
            indexing_status=status,
        )  # fmt: skip

    row("1", "commons", "https://x/commons/1", "indexed")
    row("9", "other", "https://x/shared", "indexed")
    row("3", "met", "https://x/met/3", "failed")
    commons = [mi("commons", "1"), mi("commons", "2", url="https://x/shared"), mi("commons", "4")]
    out = run(
        {"commons": Fake("commons", {"*": commons}), "met": Fake("met", {"*": [mi("met", "3")]})},
        session=session,
    )  # fmt: skip
    assert sorted(i.id for i in out) == ["cx_commons_4", "cx_met_3"]  # unindexed rows are retried
    assert out.dropped["known"] == 2


def test_drops_licences_failing_provenance() -> None:
    rows = [
        mi("commons", "1"), mi("commons", "2", lic="CC-BY-NC-4.0"),
        mi("commons", "3", lic="CC-BY-4.0", creator=None), mi("commons", "4", lic="CC-BY-4.0"),
    ]  # fmt: skip
    out = run({"commons": Fake("commons", {"*": rows})})
    assert sorted(i.id for i in out) == ["cx_commons_1", "cx_commons_4"]
    assert out.dropped["provenance"] == 2


def test_cap_round_robins_across_sources() -> None:
    a = [mi("commons", str(i)) for i in range(30)]
    b = [mi("met", str(i)) for i in range(30)]
    fakes = {"commons": Fake("commons", {"*": a}), "met": Fake("met", {"*": b})}
    out = run(fakes, max_candidates=10)
    assert len(out) == 10
    assert sum(i.source == "met" for i in out) == 5


def test_limits_per_source_and_per_call() -> None:
    f = Fake("commons", {"*": [mi("commons", str(i)) for i in range(30)]})
    run({"commons": f}, queries=["q"], limits={"commons": 4})
    assert f.calls == [("q", 4)]
    f2 = Fake("commons", {"*": []})
    run({"commons": f2}, queries=["q"], limits=7)
    assert f2.calls == [("q", 7)]


def test_timeout_marks_source_and_keeps_partial_results() -> None:
    slow = Fake("met", {"*": [mi("met", str(i)) for i in range(50)]}, per_item=0.05)
    fast = Fake("commons", {"*": [mi("commons", "1")]})
    t0 = time.monotonic()
    out = run({"met": slow, "commons": fast}, queries=["q"], timeout=0.3)
    assert time.monotonic() - t0 < 1.5
    assert out.sources["met"].status == "timeout"
    assert out.sources["commons"].status == "ok"
    assert any(i.source == "commons" for i in out)
    assert 0 < sum(i.source == "met" for i in out) < 50  # what arrived in time is kept


def test_unknown_or_disabled_sources_are_refused() -> None:
    assert search.parse_sources("commons, met ,pexels,nope,commons") == ["commons", "met"]
    with pytest.raises(ValueError):
        search.make_source("pexels", "watch")


def test_default_factory_builds_real_adapters() -> None:
    assert search.make_source("commons", "watch").name == "commons"
