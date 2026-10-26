"""Versioned ranking configuration. Persisted on each run via `RANKING_CONFIG.model_dump()`."""

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Weights(_Frozen):
    target: float = 0.35
    preservation: float = 0.35
    relevance: float = 0.20
    diversity: float = 0.10


class RelevanceMix(_Frozen):
    source_item: float = 0.6
    board_centroid: float = 0.4


class RankingConfig(_Frozen):
    version: str = "rank-2026.10-c"
    validated: bool = False
    weights: Weights = Weights()
    relevance_mix: RelevanceMix = RelevanceMix()
    reliable_confidence: float = 0.7
    pool_size: int = 200
    shortlist_size: int = 16
    result_size: int = 6
    duplicate_dhash_distance: int = 6
    color_same_max: float = 10.0
    color_different_min: float = 20.0
    shape_same_min: float = 0.85
    shape_different_max: float = 0.60


RANKING_CONFIG = RankingConfig()
