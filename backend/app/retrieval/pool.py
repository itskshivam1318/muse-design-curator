"""Candidate pool: indexed corpus items of the board's domain, ranked by embedding relevance."""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.corpus.indexer import embeddings_path
from app.db.models import CorpusAttribute, CorpusItem
from app.retrieval.config import RankingConfig
from app.validation.comparators import AttrValue


@dataclass
class PoolItem:
    item: CorpusItem
    relevance: float
    attrs: dict[str, AttrValue] = field(default_factory=dict)
    embedding: Any = None  # unit-length candidate vector, for pairwise similarity


@dataclass
class PoolMeta:
    invalid_unindexed: int = 0  # provenance-invalid items in the domain that were never fetched


class Pool(list[PoolItem]):
    """The ranked pool (a plain list) plus run-summary counts in `.meta`."""

    def __init__(self, items: list[PoolItem] | None = None, meta: PoolMeta | None = None) -> None:
        super().__init__(items or [])
        self.meta = meta or PoolMeta()


def _unit(v: Any) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64).reshape(-1)
    n = np.linalg.norm(a)
    return a / n if n else a  # type: ignore[no-any-return]


def build_pool(
    session: Session,
    board: Any,
    source_vec: Any,
    centroid_vec: Any | None,
    cfg: RankingConfig,
) -> Pool:
    domain = board.domain
    invalid_unindexed = (
        session.scalar(
            select(func.count())
            .select_from(CorpusItem)
            .where(
                CorpusItem.domain == domain,
                CorpusItem.provenance_status == "invalid",
                CorpusItem.indexing_status != "indexed",
            )
        )
        or 0
    )
    meta = PoolMeta(invalid_unindexed=invalid_unindexed)
    path = embeddings_path()
    if domain is None or not path.is_file():
        return Pool(meta=meta)
    matrix = np.asarray(np.load(path, allow_pickle=False), dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        return Pool(meta=meta)
    src = _unit(source_vec)
    cen = _unit(centroid_vec) if centroid_vec is not None else None
    mix = cfg.relevance_mix
    scored: list[PoolItem] = []
    q = select(CorpusItem).where(
        CorpusItem.domain == domain,
        CorpusItem.indexing_status == "indexed",
        CorpusItem.embedding_row.is_not(None),
    )
    for item in session.scalars(q):
        row = item.embedding_row
        if row is None or not 0 <= row < matrix.shape[0] or matrix.shape[1] != src.shape[0]:
            continue
        vec = _unit(matrix[row])
        cos_src = float(vec @ src)
        if cen is None:
            rel = cos_src
        else:
            rel = mix.source_item * cos_src + mix.board_centroid * float(vec @ cen)
        scored.append(PoolItem(item, rel, embedding=vec))
    scored.sort(key=lambda p: (-p.relevance, p.item.id))
    top = scored[: cfg.pool_size]
    if top:
        rows = session.scalars(
            select(CorpusAttribute).where(CorpusAttribute.item_id.in_([p.item.id for p in top]))
        )
        by_item: dict[str, dict[str, AttrValue]] = {}
        for r in rows:
            by_item.setdefault(r.item_id, {})[r.key] = AttrValue.from_row(r)
        for p in top:
            p.attrs = by_item.get(p.item.id, {})
    return Pool(top, meta)
