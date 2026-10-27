import io

import httpx
import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select

from app import jobs
from app.api import deps
from app.corpus.indexer import EmbeddingStore, embeddings_path
from app.corpus.sources.base import ManifestItem, item_id
from app.db.models import CorpusAttribute, CorpusItem, PartMask
from app.live import quick_index as qi
from tests.media import image_bytes


def mi(sid: str, url: str | None = None) -> ManifestItem:
    return ManifestItem(
        id=item_id("commons", sid), domain="watch", source="commons", source_id=sid,
        landing_url=f"https://c/{sid}", image_url=url or f"https://img.test/{sid}.png",
        creator_name="A", license_code="CC0-1.0", attribution_text=f"credit {sid}",
    )  # fmt: skip


def transport(images: dict[str, bytes]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        body = images.get(req.url.path.strip("/"))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def boom_providers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Any segmentation or reasoning use during a quick index is a failure."""
    used: list[str] = []

    def seg(_s: object) -> object:
        used.append("seg")
        raise AssertionError("SAM must not run in a quick index")

    def reasoning(_s: object) -> object:
        used.append("reasoning")
        raise AssertionError("the reasoning model must not run in a quick index")

    monkeypatch.setattr("app.providers.get_segmentation", seg)
    monkeypatch.setattr("app.providers.get_reasoning", reasoning)
    monkeypatch.setattr("app.extraction.service.get_segmentation", seg)
    monkeypatch.setattr("app.extraction.service.get_reasoning", reasoning)
    return used


def test_quick_item_gets_embedding_palette_and_no_sam(session, data_dir, boom_providers) -> None:  # type: ignore[no-untyped-def]
    imgs = {"a.png": image_bytes("PNG", (400, 300), 1), "b.png": image_bytes("PNG", (400, 300), 2)}
    rows = qi.quick_index(session, [mi("a", "https://img.test/a.png"), mi("b", "https://img.test/b.png")],
                          "watch", client=transport(imgs))  # fmt: skip
    assert {r.id for r in rows} == {"cx_commons_a", "cx_commons_b"}
    for r in rows:
        assert r.indexing_status == "indexed" and r.index_depth == "quick"
        assert r.sha256 and r.dhash and r.width == 400 and r.local_path
        assert isinstance(r.embedding_row, int)
        assert r.palette_json and r.palette_json[0]["hex"].startswith("#")
    store = EmbeddingStore(embeddings_path(), keep_rows=10)
    assert len(store) == 2 and {r.embedding_row for r in rows} == {0, 1}
    assert session.scalar(select(func.count()).select_from(PartMask)) == 0
    assert session.scalar(select(func.count()).select_from(CorpusAttribute)) == 0
    assert boom_providers == []


def test_resizes_to_1280_and_keeps_small_originals_byte_for_byte(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    big = image_bytes("PNG", (2000, 1000), 3)
    small = image_bytes("PNG", (500, 400), 4)
    rows = qi.quick_index(session, [mi("big", "https://img.test/big.png"), mi("small", "https://img.test/small.png")],
                          "watch", client=transport({"big.png": big, "small.png": small}))  # fmt: skip
    by = {r.id: r for r in rows}
    assert max(by["cx_commons_big"].width, by["cx_commons_big"].height) == 1280
    from app.storage import files

    assert files.abs_path(by["cx_commons_small"].local_path).read_bytes() == small
    with Image.open(io.BytesIO(files.abs_path(by["cx_commons_big"].local_path).read_bytes())) as im:
        assert max(im.size) == 1280


def test_duplicate_sha_is_not_re_added(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    same = image_bytes("PNG", (300, 300), 5)
    client = transport({"a.png": same, "b.png": same, "c.png": image_bytes("PNG", (300, 300), 6)})
    first = qi.quick_index(
        session,
        [mi("a", "https://img.test/a.png"), mi("b", "https://img.test/b.png")],
        "watch",
        client=client,
    )
    assert [r.id for r in first] == ["cx_commons_a"]  # b has the same bytes as a
    again = qi.quick_index(
        session,
        [mi("b", "https://img.test/b.png"), mi("c", "https://img.test/c.png")],
        "watch",
        client=client,
    )
    assert [r.id for r in again] == ["cx_commons_c"]
    assert session.scalar(select(func.count()).select_from(CorpusItem)) == 2
    assert len(EmbeddingStore(embeddings_path(), keep_rows=10)) == 2


def test_bad_downloads_are_skipped(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    rows = qi.quick_index(
        session, [mi("ok", "https://img.test/ok.png"), mi("missing", "https://img.test/nope.png"),
                  mi("text", "https://img.test/t.png"), mi("ftp", "ftp://img.test/x.png")],
        "watch", client=transport({"ok.png": image_bytes("PNG", (300, 300), 7), "t.png": b"not an image"}),
    )  # fmt: skip
    assert [r.id for r in rows] == ["cx_commons_ok"]
    assert session.get(CorpusItem, "cx_commons_missing") is None


def test_licence_failures_are_never_stored(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    bad = mi("nc", "https://img.test/a.png").model_copy(update={"license_code": "CC-BY-NC-4.0"})
    assert qi.quick_index(session, [bad], "watch", client=transport({"a.png": image_bytes()})) == []
    assert session.scalar(select(func.count()).select_from(CorpusItem)) == 0


def test_downloads_are_bounded_to_six_at_once(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    import threading
    import time

    live = {"now": 0, "max": 0}
    lock = threading.Lock()

    def handler(req: httpx.Request) -> httpx.Response:
        with lock:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
        time.sleep(0.05)
        with lock:
            live["now"] -= 1
        n = int(req.url.path.strip("/").split(".")[0])
        return httpx.Response(200, content=image_bytes("PNG", (260, 260), n))

    items = [mi(str(n), f"https://img.test/{n}.png") for n in range(12)]
    rows = qi.quick_index(
        session, items, "watch", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert len(rows) == 12 and 2 <= live["max"] <= qi.DOWNLOAD_CONCURRENCY == 6


def test_deepen_upgrades_to_full_with_attributes(client, data_dir) -> None:  # type: ignore[no-untyped-def]
    session = deps._factory()()
    rows = qi.quick_index(session, [mi("a", "https://img.test/a.png")], "watch",
                          client=transport({"a.png": image_bytes("PNG", (400, 400), 8)}))  # fmt: skip
    assert rows[0].index_depth == "quick"
    jobs.register("deepen_item", qi.deepen_item)
    jobs.enqueue("deepen_item", corpus_item_id="cx_commons_a")  # JOBS_SYNC runs it inline
    session.expire_all()
    row = session.get(CorpusItem, "cx_commons_a")
    assert row.index_depth == "full"
    assert session.scalar(select(func.count()).select_from(CorpusAttribute)) > 0
    assert qi.deepen(session, "cx_commons_a") is False  # already full
    session.close()


def test_matrix_rows_line_up_with_database(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    qi.quick_index(session, [mi("a", "https://img.test/a.png")], "watch",
                   client=transport({"a.png": image_bytes("PNG", (300, 300), 9)}))  # fmt: skip
    m = np.load(embeddings_path())
    row = session.get(CorpusItem, "cx_commons_a")
    assert m.shape[0] == 1 and row.embedding_row == 0
    assert abs(float(np.linalg.norm(m[0])) - 1.0) < 1e-5


def _redirecting(routes: dict[str, httpx.Response], seen: list[str]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return routes.get(str(req.url), httpx.Response(404))

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_redirect_to_a_private_address_is_dropped(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []
    meta = "http://169.254.169.254/latest/meta-data/x.png"
    client = _redirecting(
        {
            "https://img.test/a.png": httpx.Response(302, headers={"location": meta}),
            "https://img.test/b.png": httpx.Response(302, headers={"location": "http://10.0.0.5/b.png"}),
            meta: httpx.Response(200, content=image_bytes("PNG", (300, 300), 3)),
            "http://10.0.0.5/b.png": httpx.Response(200, content=image_bytes("PNG", (300, 300), 4)),
        },
        seen,
    )
    rows = qi.quick_index(session, [mi("a"), mi("b")], "watch", client=client)
    assert rows == []
    assert all("169.254" not in u and "10.0.0.5" not in u for u in seen)  # never requested


def test_redirect_to_a_public_host_is_followed_and_capped_at_three(session, data_dir) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []
    hop = lambda n: f"https://cdn.test/{n}.png"
    client = _redirecting(
        {
            "https://img.test/ok.png": httpx.Response(301, headers={"location": hop(1)}),
            hop(1): httpx.Response(200, content=image_bytes("PNG", (300, 300), 5)),
            "https://img.test/far.png": httpx.Response(302, headers={"location": hop(10)}),
            **{hop(n): httpx.Response(302, headers={"location": hop(n + 1)}) for n in range(10, 14)},
            hop(14): httpx.Response(200, content=image_bytes("PNG", (300, 300), 6)),
        },
        seen,
    )
    rows = qi.quick_index(session, [mi("ok"), mi("far")], "watch", client=client)
    assert [r.id for r in rows] == [item_id("commons", "ok")]
    assert hop(14) not in seen  # more than three redirects: dropped before the fourth hop


def test_default_client_pins_the_vetted_address(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.ingest import links

    pinned: list[str] = []

    def fake_transport(ip: str) -> httpx.BaseTransport:
        pinned.append(ip)
        return httpx.MockTransport(lambda r: httpx.Response(200, content=b"x"))

    monkeypatch.setattr(links, "pinned_transport", fake_transport)
    assert qi._download(None, "https://img.test/a.png", 100) == b"x"
    assert pinned == ["93.184.216.34"]
