"""Domain voting: each embedded board item votes for its nearest curated-domain prototype."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import data_dir, get_settings
from app.db.models import CorpusItem
from app.domain.lens import LENS_DIR

AMBIGUOUS_SECOND_SHARE = 0.4


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(n == 0, 1.0, n)  # type: ignore[no-any-return]


def _prototypes(session: Session) -> dict[str, np.ndarray]:
    path = data_dir(get_settings()) / "embeddings.npy"
    if not path.is_file():
        return {}
    matrix = np.asarray(np.load(path, allow_pickle=False), dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        return {}
    curated = {p.stem for p in LENS_DIR.glob("*.json")}
    q = select(CorpusItem.domain, CorpusItem.embedding_row).where(
        CorpusItem.indexing_status == "indexed", CorpusItem.embedding_row.is_not(None)
    )
    rows: dict[str, list[int]] = {}
    for domain, row in session.execute(q):
        if row is not None and domain in curated and 0 <= row < matrix.shape[0]:
            rows.setdefault(domain, []).append(row)
    out: dict[str, np.ndarray] = {}
    for domain, idx in rows.items():
        mean = _unit(_unit(matrix[idx]).mean(axis=0, keepdims=True))[0]
        out[domain] = mean
    return out


def domain_votes(session: Session, items: Sequence[Any]) -> dict[str, float]:
    """Vote shares per curated domain, or {} when no prototypes/embeddings exist."""
    protos = _prototypes(session)
    if not protos:
        return {}
    names = sorted(protos)
    proto = np.stack([protos[n] for n in names])
    counts: Counter[str] = Counter()
    for item in items:
        emb = getattr(item, "embedding_json", None)
        if not emb:
            continue
        v = np.asarray(emb, dtype=np.float64)
        if v.ndim != 1 or v.shape[0] != proto.shape[1]:
            continue
        norm = np.linalg.norm(v)
        if norm == 0:
            continue
        counts[names[int(np.argmax(proto @ (v / norm)))]] += 1
    total = sum(counts.values())
    return {d: c / total for d, c in counts.items()} if total else {}


def ambiguous_candidates(votes: dict[str, float]) -> list[str] | None:
    """The two leading domains when the runner-up holds at least 40% of the votes."""
    ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) >= 2 and ranked[1][1] >= AMBIGUOUS_SECOND_SHARE:
        return [ranked[0][0], ranked[1][0]]
    return None
