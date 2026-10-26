"""Shortlist and greedy diversity-aware selection."""

from dataclasses import replace

from app.domain.variation import VariationSpec
from app.retrieval.config import RankingConfig
from app.retrieval.scores import Candidate, Scores, pair_similarity, total_score


def _order(c: Candidate) -> tuple[float, float, str]:
    return (-c.scores.total, -c.scores.relevance, c.pool.item.id)


def shortlist(cands: list[Candidate], cfg: RankingConfig) -> list[Candidate]:
    top = sorted(cands, key=_order)[: cfg.shortlist_size]
    return [Candidate(c.pool, _with(c, 1.0, cfg), None) for c in top]


def _with(c: Candidate, diversity: float, cfg: RankingConfig) -> Scores:
    s = replace(c.scores, diversity=diversity)
    return replace(s, total=total_score(s, cfg))


def select_diverse(
    cands: list[Candidate], spec: VariationSpec, cfg: RankingConfig, k: int
) -> list[Candidate]:
    remaining = list(cands)
    chosen: list[Candidate] = []
    while remaining and len(chosen) < k:
        best: Candidate | None = None
        for c in remaining:
            div = (
                1.0
                if not chosen
                else 1.0 - max(pair_similarity(c.pool, s.pool, spec, cfg) for s in chosen)
            )
            trial = Candidate(c.pool, _with(c, div, cfg), None)
            if best is None or _order(trial) < _order(best):
                best = trial
        assert best is not None
        remaining = [c for c in remaining if c.pool is not best.pool]
        best.rank = len(chosen) + 1
        chosen.append(best)
    return chosen
