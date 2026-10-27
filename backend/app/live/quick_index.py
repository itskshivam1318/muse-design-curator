"""Quick index for live candidates, and the background job that deepens them to a full index.

A quick item has its image (<= 1280 px), hashes, one embedding row and a whole-image palette, and
nothing else: no part masks and no attributes. The validator reads only what it needs from such an
item; `deepen_item` later runs the normal full indexing and sets `index_depth='full'`.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import jobs
from app.config import get_settings
from app.corpus import hashing
from app.corpus.indexer import EmbeddingStore, _store_attributes, embeddings_path
from app.corpus.provenance import check_provenance
from app.corpus.sources.base import ManifestItem, user_agent
from app.db.models import CorpusItem
from app.db.repos import corpus as corpus_repo
from app.ingest.sniff import sniff_image
from app.measure.palette import masked_palette, to_rgb_array
from app.providers import get_embedder
from app.storage import files

log = logging.getLogger(__name__)

THUMB_MAX_SIDE = 1280
DOWNLOAD_CONCURRENCY = 6
DEEPEN_JOB = "deepen_item"
MAX_DEEPEN_PER_RUN = 16


@dataclass
class QuickProviders:
    embedder: Any = None


def _download(client: httpx.Client, url: str, limit: int) -> bytes:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("UNSUPPORTED_URL")
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf += chunk
            if len(buf) > limit:
                raise ValueError("IMAGE_TOO_LARGE")
    return bytes(buf)


def _fit(data: bytes) -> tuple[bytes, str, int, int]:
    """(bytes, ext, width, height): the original when it fits, else a resized copy (<= 1280 px)."""
    kind = sniff_image(data)
    if kind is None:
        raise ValueError("NOT_AN_IMAGE")
    _mime, ext = kind
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        w, h = im.size
        if max(w, h) <= THUMB_MAX_SIDE:
            return data, ext, w, h
        small = im.copy()
    small.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if "A" in small.getbands():
        small.save(buf, "PNG")
        ext = "png"
    else:
        small.convert("RGB").save(buf, "JPEG", quality=90)
        ext = "jpg"
    return buf.getvalue(), ext, small.width, small.height


def _metadata(item: ManifestItem) -> dict[str, Any]:
    return {
        "domain": item.domain, "source": item.source, "source_id": item.source_id,
        "landing_url": item.landing_url, "image_url": item.image_url,
        "creator_name": item.creator_name, "license_code": item.license_code,
        "license_url": item.license_url, "attribution_text": item.attribution_text,
        "fetched_at": item.fetched_at,
    }  # fmt: skip


def quick_index(
    session: Session,
    items: list[ManifestItem],
    domain: str,
    providers: QuickProviders | None = None,
    *,
    client: httpx.Client | None = None,
) -> list[CorpusItem]:
    """Persist each new item as an indexed, quick-depth corpus row; returns the rows added.

    Items that fail to download or decode are skipped (nothing is stored for them). An image
    whose sha256 already belongs to another corpus row is not added again.
    """
    settings = get_settings()
    providers = providers or QuickProviders()
    valid = [i for i in items if check_provenance(i)[0] == "valid"]
    if not valid:
        return []
    http = client or httpx.Client(
        timeout=15, headers={"User-Agent": user_agent(settings)}, follow_redirects=True
    )
    limit = settings.MAX_UPLOAD_BYTES

    # download in parallel (bounded); everything touching the session stays on this thread
    def get(item: ManifestItem) -> tuple[bytes, str, int, int] | None:
        try:
            return _fit(_download(http, item.image_url, limit))
        except Exception as exc:  # noqa: BLE001 - one bad image must not stop the rest
            log.info("live image %s skipped: %s", item.id, exc)
            return None

    with ThreadPoolExecutor(max_workers=DOWNLOAD_CONCURRENCY, thread_name_prefix="quick") as ex:
        fetched = list(ex.map(get, valid))

    top = session.scalar(select(func.max(CorpusItem.embedding_row)))
    store = EmbeddingStore(embeddings_path(), keep_rows=0 if top is None else top + 1)
    embedder = providers.embedder or get_embedder(settings)

    seen_sha: set[str] = set()
    prepared: list[tuple[ManifestItem, bytes, str, int, int, str, str]] = []
    for item, got in zip(valid, fetched, strict=True):
        if got is None:
            continue
        data, ext, w, h = got
        sha = hashing.sha256(data)
        taken = session.scalar(
            select(CorpusItem.id).where(CorpusItem.sha256 == sha, CorpusItem.id != item.id)
        )
        if taken is not None or sha in seen_sha:
            continue  # the same image is already in the corpus
        seen_sha.add(sha)
        try:
            dh = hashing.dhash(data)
        except Exception as exc:  # noqa: BLE001
            log.info("live image %s skipped: %s", item.id, exc)
            continue
        prepared.append((item, data, ext, w, h, sha, dh))
    if not prepared:
        return []

    vectors = embedder.embed_images([p[1] for p in prepared])
    added: list[CorpusItem] = []
    for (item, data, ext, w, h, sha, dh), vec in zip(prepared, vectors, strict=True):
        with Image.open(io.BytesIO(data)) as im:
            files.save_thumb(im, sha)
        local = files.save_original(data, sha, ext)
        palette = masked_palette(to_rgb_array(data), None)
        row = corpus_repo.get(session, item.id)
        fields = {**_metadata(item), "provenance_status": "valid", "provenance_issue": None}
        if row is None:
            row = corpus_repo.create(session, id=item.id, indexing_status="pending", **fields)
        else:
            corpus_repo.update(session, item.id, **fields)
        erow = store.put(row.embedding_row, vec)
        corpus_repo.update(
            session, item.id, sha256=sha, dhash=dh, width=w, height=h, local_path=local,
            embedding_row=erow, indexing_status="indexed", index_depth="quick",
            palette_json=palette,
        )  # fmt: skip
        added.append(row)
    store.flush()  # rows on disk before the commit that points at them
    session.commit()
    return added


# ---- deepening ----


def deepen(session: Session, corpus_item_id: str) -> bool:
    """Run the normal full indexing (parts + attributes) on a quick item; True when deepened."""
    row = corpus_repo.get(session, corpus_item_id)
    if row is None or row.index_depth != "quick" or row.indexing_status != "indexed":
        return False
    if not row.local_path or not row.sha256:
        return False
    path = files.abs_path(row.local_path)
    if not path.is_file():
        return False
    with session.begin_nested():
        _store_attributes(session, row.id, row.domain, path.read_bytes(), row.sha256)
    corpus_repo.update(session, row.id, index_depth="full")
    session.commit()
    return True


def deepen_item(corpus_item_id: str) -> None:
    """Background job: deepen one item in its own session."""
    from app.api import deps

    with deps._factory()() as session:
        try:
            deepen(session, corpus_item_id)
        except Exception:
            session.rollback()
            log.exception("deepening %s failed", corpus_item_id)


jobs.register(DEEPEN_JOB, deepen_item)
