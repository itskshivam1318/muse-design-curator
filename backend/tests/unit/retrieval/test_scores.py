import math
from types import SimpleNamespace

import pytest

from app.domain.kinds import EnumSpec, OrdinalSpec
from app.domain.variation import Nudge, ProtectedSpec, VariationRequest, VariationSpec
from app.retrieval.config import RANKING_CONFIG as CFG
from app.retrieval.pool import PoolItem
from app.retrieval.scores import pair_similarity, preservation_score, relevance_score, target_score
from app.validation.comparators import AttrValue

ENUM = EnumSpec(key="t", label="T", category="c", vocabulary=["a", "b", "c"])
ORD = OrdinalSpec(key="o", label="O", category="c", scale=["compact", "regular", "airy"])


def av(v, conf=0.9, status="extracted"):
    return AttrValue(v, conf, status)


def spec(mode, tspec=ENUM, values=(), target_value=None, protected=(), nudge=None):
    req = VariationRequest(
        source_item_id="s", target_key=tspec.key, mode=mode, nudge=nudge,
        target_values=[str(v) for v in values],
    )  # fmt: skip
    return VariationSpec(
        request=req, target_spec=tspec, target_value=target_value, values=tuple(values),
        protected=tuple(protected),
    )  # fmt: skip


def test_weights_sum_to_one():
    w = CFG.weights
    assert math.isclose(w.target + w.preservation + w.relevance + w.diversity, 1.0)


def test_explore_scores():
    s = spec("explore", target_value="a")
    assert target_score(s, av("a"), av("b"), CFG) == 1
    assert target_score(s, av("a"), None, CFG) == 0
    assert target_score(s, av("a"), av(None), CFG) == 0
    assert target_score(s, av("a"), av("b", 0.5), CFG) == 0.25  # unreliable -> unknown


def test_explore_colour_band():
    from app.domain.kinds import ColorSpec

    cs = ColorSpec(key="c", label="C", category="c")
    s = spec("explore", cs, target_value="x")
    src = AttrValue("x", 1.0, "confirmed", {"lab": [50, 0, 0]})

    def cand(l_shift):
        return AttrValue("y", 0.9, "extracted", {"lab": [50 + l_shift, 0, 0]})

    from app.measure.palette import delta_e

    de = delta_e((50, 0, 0), (65, 0, 0))
    assert 10 < de < 20
    assert target_score(s, src, cand(15), CFG) == pytest.approx(0.5 * (de - 10) / 10)
    assert target_score(s, src, cand(60), CFG) == 1


def test_prefer_and_avoid():
    p = spec("prefer", values=("b", "c"))
    assert target_score(p, av("a"), av("c"), CFG) == 1
    assert target_score(p, av("a"), av("a"), CFG) == 0
    assert target_score(p, av("a"), av("b", 0.5), CFG) == 0.25  # unreliable -> unknown
    assert target_score(p, av("a"), None, CFG) == 0
    a = spec("avoid", values=("b",))
    assert target_score(a, av("a"), av("c"), CFG) == 1
    assert target_score(a, av("a"), av("c", 0.4), CFG) == pytest.approx(0.2)
    assert target_score(a, av("a"), None, CFG) == 0


def test_nudge_more_prefers_airy():
    s = spec("nudge", ORD, target_value="regular", nudge=Nudge(direction="more", steps=1))
    assert target_score(s, av("regular"), av("airy"), CFG) == 1
    assert target_score(s, av("regular"), av("compact"), CFG) == 0
    assert target_score(s, av("regular"), av("regular"), CFG) == 0
    s2 = spec("nudge", ORD, target_value="compact", nudge=Nudge(direction="more", steps=1))
    assert target_score(s2, av("compact"), av("airy"), CFG) == 0.5


def prot(value="mid"):
    return ProtectedSpec(key="p", spec=ORD, value=value)


def test_preservation():
    s = spec("explore", target_value="a", protected=(prot("regular"),))
    src = {"p": av("regular")}
    assert preservation_score(s, src, {"p": av("regular")}, CFG) == 1
    assert preservation_score(s, src, {"p": av("regular", 0.4)}, CFG) == pytest.approx(0.2)
    assert preservation_score(s, src, {}, CFG) == 0
    assert preservation_score(s, src, {"p": av("airy")}, CFG) == 0
    e = spec("explore", target_value="a")
    assert preservation_score(e, {}, {}, CFG) == 1


def test_relevance_mapping():
    assert relevance_score(1.0) == 1
    assert relevance_score(-1.0) == 0
    assert relevance_score(0.0) == 0.5


def test_pair_similarity():
    s = spec("explore", target_value="a")
    a = PoolItem(SimpleNamespace(id="a"), 0.5, {"t": av("b")}, [1.0, 0.0])
    b = PoolItem(SimpleNamespace(id="b"), 0.5, {"t": av("b")}, [0.0, 1.0])
    assert pair_similarity(a, b, s, CFG) == pytest.approx(0.5)
    b2 = PoolItem(SimpleNamespace(id="c"), 0.5, {"t": av("c")}, [0.0, 1.0])
    assert pair_similarity(a, b2, s, CFG) == pytest.approx(0.0)


def test_pair_similarity_clamped_for_opposite_vectors():
    s = spec("explore", target_value="a")
    a = PoolItem(SimpleNamespace(id="a"), 0.5, {"t": av("b")}, [1.0, 0.0])
    b = PoolItem(SimpleNamespace(id="b"), 0.5, {"t": av("c")}, [-1.0, 0.0])
    assert pair_similarity(a, b, s, CFG) == 0.0
