"""Corpus indexer: fetch each manifest image once and precompute everything retrieval needs.

Per item: sha256, dHash, size, part masks, measured and model-read attributes for the domain's
curated lens, and one L2-normalised embedding row in `<DATA_DIR>/embeddings.npy`. Re-runs upsert by
item id and skip items that are already indexed. The embedding file is replaced atomically and
always written before the database commit that refers to its rows.
"""

import io
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import data_dir, get_settings
from app.corpus import hashing
from app.corpus.provenance import check_provenance
from app.corpus.sources.base import ManifestItem, user_agent
from app.db.models import CorpusItem
from app.db.repos import corpus as corpus_repo
from app.domain.lens import load_curated_lens
from app.extraction import service as extraction
from app.ingest.sniff import sniff_image
from app.measure.palette import to_rgb_array
from app.providers import get_embedder
from app.storage import files

log = logging.getLogger(__name__)

BATCH_SIZE = 25


@dataclass
class IndexReport:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    invalid: int = 0
    reasons: dict[str, str] = field(default_factory=dict)


def read_manifest(path: Path) -> list[ManifestItem]:
    items: dict[str, ManifestItem] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = ManifestItem.model_validate(json.loads(line))
            items[item.id] = item  # the last line for an id wins
    return list(items.values())


def embeddings_path() -> Path:
    return data_dir(get_settings()) / "embeddings.npy"


class EmbeddingStore:
    """The float32 matrix on disk; the database stores each item's row index."""

    def __init__(self, path: Path, keep_rows: int) -> None:
        self.path = path
        self.matrix: np.ndarray | None = None
        if path.is_file():
            m = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32)
            if m.ndim == 2:
                self.matrix = m[:keep_rows]  # drop rows an interrupted run wrote but never kept
        self.dirty = False

    def __len__(self) -> int:
        return 0 if self.matrix is None else int(self.matrix.shape[0])

    def put(self, row: int | None, vector: np.ndarray) -> int:
        v = np.asarray(vector, dtype=np.float32).reshape(-1)
        v = v / (np.linalg.norm(v) or 1.0)
        if self.matrix is None:
            self.matrix = np.zeros((0, v.shape[0]), dtype=np.float32)
        if v.shape[0] != self.matrix.shape[1]:
            raise ValueError(
                f"embedding dimension {v.shape[0]} does not match the stored {self.matrix.shape[1]}"
                f"; delete {self.path} and re-index with the new embedder"
            )
        if row is None or row >= len(self):
            row = len(self)
            self.matrix = np.vstack([self.matrix, v[None, :]])
        else:
            self.matrix[row] = v
        self.dirty = True
        return row

    def has(self, row: int | None) -> bool:
        return row is not None and 0 <= row < len(self)

    def flush(self) -> None:
        if not self.dirty or self.matrix is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                np.save(f, self.matrix, allow_pickle=False)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self.dirty = False


def _fetch(item: ManifestItem, base_dir: Path, client: httpx.Client) -> bytes:
    limit = get_settings().MAX_UPLOAD_BYTES
    if urlparse(item.image_url).scheme in ("http", "https"):
        resp = client.get(item.image_url)
        resp.raise_for_status()
        data = resp.content
    else:
        data = (base_dir / item.image_url).read_bytes()
    if len(data) > limit:
        raise ValueError("IMAGE_TOO_LARGE")
    return data


def _metadata(item: ManifestItem) -> dict[str, object]:
    return {
        "domain": item.domain, "source": item.source, "source_id": item.source_id,
        "landing_url": item.landing_url, "image_url": item.image_url,
        "creator_name": item.creator_name, "license_code": item.license_code,
        "license_url": item.license_url, "attribution_text": item.attribution_text,
        "fetched_at": item.fetched_at,
    }  # fmt: skip


def _store_attributes(session: Session, corpus_id: str, domain: str, data: bytes, sha: str) -> None:
    lens = load_curated_lens(domain, get_settings().SHAPE_KIND_ENABLED)
    if lens is None:
        return
    rgb = to_rgb_array(data)
    grounded = extraction.ground_parts(session, lens, data, sha, rgb.shape[:2])
    records = extraction.measure_attributes(lens, rgb, grounded)
    records += extraction.model_extract(session, lens, data, sha, "")
    for rec in records:
        corpus_repo.set_attribute(
            session, corpus_id, rec.key, value_json=rec.value, confidence=rec.confidence,
            source=rec.source, evidence_json=rec.evidence.model_dump(mode="json"),
            measured_json=rec.measured,
        )  # fmt: skip


def index_corpus(
    session: Session,
    domain: str,
    manifest_path: Path,
    client: httpx.Client | None = None,
    batch_size: int = BATCH_SIZE,
    limit: int | None = None,
) -> IndexReport:
    """Index the manifest's items for `domain` (an evenly spaced `limit` of them, if given).

    Commits once per batch (see module docstring).
    """
    manifest_path = Path(manifest_path)
    base_dir = manifest_path.parent
    report = IndexReport()
    http = client or httpx.Client(
        timeout=httpx.Timeout(15.0, connect=10.0),
        headers={"User-Agent": user_agent(get_settings())},
        follow_redirects=True,
    )
    top = session.scalar(select(func.max(CorpusItem.embedding_row)))
    store = EmbeddingStore(embeddings_path(), keep_rows=0 if top is None else top + 1)
    embedder = get_embedder(get_settings())

    def checkpoint() -> None:
        store.flush()  # rows on disk before the commit that points at them
        session.commit()

    done = 0
    todo = [i for i in read_manifest(manifest_path) if i.domain == domain]
    if limit is not None and 0 < limit < len(todo):
        # an evenly spaced subset keeps every query/source represented
        todo = [todo[k * len(todo) // limit] for k in range(limit)]
    for item in todo:
        status, issue = check_provenance(item)
        row = corpus_repo.get(session, item.id)
        fields = {**_metadata(item), "provenance_status": status, "provenance_issue": issue}
        if row is None:
            row = corpus_repo.create(session, id=item.id, indexing_status="pending", **fields)
        else:
            corpus_repo.update(session, item.id, **fields)
        if status == "invalid":
            # no rights, no processing: never fetched or embedded. An item that was already
            # indexed keeps its row; retrieval excludes it through provenance_status.
            if row.indexing_status != "indexed":
                corpus_repo.update(session, item.id, indexing_status="pending")
            report.invalid += 1
            report.reasons[item.id] = issue or "INVALID"
            continue
        if (
            row.indexing_status == "indexed"
            and store.has(row.embedding_row)
            and row.local_path
            and files.abs_path(row.local_path).is_file()
        ):
            report.skipped += 1
            continue
        try:
            data = _fetch(item, base_dir, http)
            if sniff_image(data) is None:
                raise ValueError("NOT_AN_IMAGE")
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                width, height = im.size
                thumb_src = im.copy()
            sha, dh = hashing.sha256(data), hashing.dhash(data)
            _mime, ext = sniff_image(data)  # type: ignore[misc]
            local = files.save_original(data, sha, ext)
            files.save_thumb(thumb_src, sha)
            vector = embedder.embed_images([data])[0]
            with session.begin_nested():
                _store_attributes(session, item.id, domain, data, sha)
            erow = store.put(row.embedding_row, vector)
            corpus_repo.update(
                session, item.id, sha256=sha, dhash=dh, width=width, height=height,
                local_path=local, embedding_row=erow, indexing_status="indexed",
            )  # fmt: skip
            report.indexed += 1
        except Exception as exc:  # noqa: BLE001 - one bad item must not stop the run
            log.warning("indexing %s failed: %s", item.id, exc)
            corpus_repo.update(session, item.id, indexing_status="failed")
            report.failed += 1
            report.reasons[item.id] = type(exc).__name__ if not str(exc) else str(exc)
        done += 1
        if done % batch_size == 0:
            checkpoint()
    checkpoint()
    return report
