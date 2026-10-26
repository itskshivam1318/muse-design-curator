import math
from types import SimpleNamespace

from app.domain.kinds import EnumSpec
from app.domain.variation import VariationRequest, VariationSpec
from app.retrieval.config import RANKING_CONFIG as CFG
from app.retrieval.pool import PoolItem
from app.retrieval.scores import score_candidate
from app.retrieval.select import select_diverse, shortlist
from app.validation.comparators import AttrValue

ENUM = EnumSpec(key="t", label="T", category="c", vocabulary=["blue", "green", "red"])
SPEC = VariationSpec(
    request=VariationRequest(source_item_id="s", target_key="t", mode="prefer", target_values=["blue", "green"]),
    target_spec=ENUM,
    values=("blue", "green"),
)  # fmt: skip


def vec(deg):
    r = math.radians(deg)
    return [math.cos(r), math.sin(r)]


def pi(id_, rel, colour, v):
    return PoolItem(SimpleNamespace(id=id_), rel, {"t": AttrValue(colour, 0.9, "extracted")}, v)


def cands(items):
    return [score_candidate(p, SPEC, {}, CFG) for p in items]


def test_a_c_b_order():
    a_vec = vec(0)
    b_vec = vec(math.degrees(math.acos(0.98)))
    c_vec = vec(math.degrees(math.acos(0.85)))
    A = pi("A", 0.90, "blue", a_vec)
    B = pi("B", 0.89, "blue", b_vec)
    C = pi("C", 0.80, "green", c_vec)
    out = select_diverse(cands([B, C, A]), SPEC, CFG, 3)
    assert [c.pool.item.id for c in out] == ["A", "C", "B"]
    assert [c.rank for c in out] == [1, 2, 3]
    assert out[0].scores.diversity == 1


def test_centroid_relevance_changes_order():
    x = pi("x", 0.2, "blue", vec(0))
    y = pi("y", 0.6, "blue", vec(90))
    out = select_diverse(cands([x, y]), SPEC, CFG, 2)
    assert out[0].pool.item.id == "y"


def test_deterministic_and_tiebreak():
    items = [pi(i, 0.5, "blue", vec(0)) for i in ("b", "a", "c")]
    one = [c.pool.item.id for c in select_diverse(cands(items), SPEC, CFG, 3)]
    two = [c.pool.item.id for c in select_diverse(cands(items[::-1]), SPEC, CFG, 3)]
    assert one == two == ["a", "b", "c"]


def test_at_most_k_and_shortlist():
    items = [pi(str(i).zfill(3), 0.5 + i / 1000, "blue", vec(i)) for i in range(30)]
    cs = cands(items)
    sl = shortlist(cs, CFG)
    assert len(sl) == CFG.shortlist_size
    assert all(c.scores.diversity == 1 for c in sl)
    assert len(select_diverse(sl, SPEC, CFG, 6)) == 6
    assert len(select_diverse(cands(items[:2]), SPEC, CFG, 6)) == 2


def test_diversity_stays_in_unit_range_for_opposite_vectors():
    out = select_diverse(
        cands([pi("a", 0.9, "blue", vec(0)), pi("b", 0.8, "green", vec(180))]), SPEC, CFG, 2
    )
    assert all(0 <= c.scores.diversity <= 1 and 0 <= c.scores.total <= 1 for c in out)
    assert out[1].scores.diversity == 1
