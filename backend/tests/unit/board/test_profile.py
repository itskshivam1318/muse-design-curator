from types import SimpleNamespace as NS
from typing import Any

from app.board.profile import BoardProfile, compute_profile
from app.domain.lens import LensSpec

LENS = LensSpec.model_validate(
    {
        "id": "thing@1", "domain": "thing", "label": "Thing", "origin": "edited",
        "parts": [],
        "attributes": [
            {"key": "finish", "label": "Finish", "category": "c", "kind": "enum",
             "vocabulary": ["brushed", "polished"]},
            {"key": "hue", "label": "Hue", "category": "c", "kind": "enum",
             "vocabulary": ["blue", "green"]},
            {"key": "size_mm", "label": "Size", "category": "c", "kind": "number",
             "unit": "mm", "min": 0, "max": 100, "tolerance": 5},
            {"key": "accent", "label": "Accent", "category": "c", "kind": "color"},
            {"key": "note", "label": "Note", "category": "c", "kind": "text"},
        ],
    }
)  # fmt: skip


def item(i: str, role: str = "reference", emb: list[float] | None = None) -> Any:
    return NS(id=i, role=role, embedding_json=emb)


def attr(key: str, value: Any, kind: str = "enum", conf: float = 0.9, **kw: Any) -> Any:
    d: dict[str, Any] = {
        "key": key, "kind": kind, "value_json": value, "confidence": conf,
        "status": "auto", "enabled": True, "measured_json": None, "label": key,
    }  # fmt: skip
    d.update(kw)
    return NS(**d)


def run(items: list[Any], attrs: dict[str, list[Any]], votes: dict[str, float] | None = None):
    return compute_profile(items, attrs, LENS, votes or {})


def test_three_of_four_brushed_is_signal() -> None:
    items = [item(f"i{n}") for n in range(4)]
    vals = ["brushed", "brushed", "brushed", "polished"]
    attrs = {f"i{n}": [attr("finish", v)] for n, v in enumerate(vals)}
    p = run(items, attrs)
    assert isinstance(p, BoardProfile)
    assert [s.key for s in p.signals] == ["finish"]
    assert p.signals[0].modal_value == "brushed"
    a = p.attributes["finish"]
    assert (
        a.n_known == 4
        and a.consistency == 0.75
        and a.distribution
        == {
            "brushed": 3,
            "polished": 1,
        }
    )
    assert not p.tensions


def test_two_blue_two_green_is_tension_not_signal() -> None:
    items = [item(f"i{n}") for n in range(4)]
    attrs = {f"i{n}": [attr("hue", v)] for n, v in enumerate(["blue", "blue", "green", "green"])}
    p = run(items, attrs)
    assert [t.key for t in p.tensions] == ["hue"]
    assert sorted(p.tensions[0].values) == ["blue", "green"]
    assert not p.signals


def test_counter_example_values_become_counter_signals() -> None:
    items = [item("a"), item("b"), item("c"), item("x", role="counter_example")]
    attrs = {
        "a": [attr("finish", "brushed")], "b": [attr("finish", "brushed")],
        "c": [attr("finish", "brushed")], "x": [attr("finish", "polished")],
    }  # fmt: skip
    p = run(items, attrs)
    assert [(c.key, c.value) for c in p.counter_signals] == [("finish", "polished")]
    assert p.attributes["finish"].distribution == {"brushed": 3}


def test_unreliable_and_disabled_values_do_not_count() -> None:
    items = [item(f"i{n}") for n in range(4)]
    attrs = {
        "i0": [attr("finish", "brushed", conf=0.5)],
        "i1": [attr("finish", "brushed", conf=0.5, status="edited")],
        "i2": [attr("finish", "brushed", enabled=False)],
        "i3": [attr("finish", None)],
    }
    assert run(items, attrs).attributes["finish"].n_known == 1


def test_mixed_domain_votes() -> None:
    p = run([item("a")], {}, {"watch": 0.6, "interior": 0.4})
    assert p.domain_votes.mixed is True
    assert p.domain_votes.candidates == ["watch", "interior"]
    assert run([item("a")], {}, {"watch": 0.8, "interior": 0.2}).domain_votes.mixed is False


def test_number_color_text_and_centroid() -> None:
    items = [item("a", emb=[3.0, 4.0]), item("b", emb=[0.0, 2.0]), item("c", emb=[1, 0])]
    sizes = [40, 42, 44]
    attrs = {
        i.id: [
            attr("size_mm", s, "number"),
            attr("note", f"text {i.id}", "text"),
            attr("accent", "red", "color", measured_json={"lab": [50.0, 60.0, 40.0], "hex": "#C0392B"}),
        ]
        for i, s in zip(items, sizes, strict=True)
    }  # fmt: skip
    p = run(items, attrs)
    n = p.attributes["size_mm"]
    assert n.median == 42 and n.iqr == 2 and n.consistency == 1.0
    assert p.attributes["note"].values == ["text a", "text b", "text c"]
    assert p.attributes["note"].consistency is None
    assert "note" not in [s.key for s in p.signals]
    clusters = p.attributes["accent"].clusters
    assert len(clusters) == 1 and clusters[0].count == 3 and clusters[0].hex
    assert p.attributes["accent"].consistency == 1.0
    assert p.centroid is not None and len(p.centroid) == 2
    # mean of unit vectors (0.6,0.8),(0,1),(1,0), renormalised
    assert abs(sum(c * c for c in p.centroid) - 1.0) < 1e-5


def test_distant_colours_form_separate_clusters() -> None:
    items = [item(f"i{n}") for n in range(4)]
    labs = [[50, 70, 50], [50, 70, 50], [30, -50, -60], [30, -50, -60]]
    attrs = {
        f"i{n}": [attr("accent", "x", "color", measured_json={"lab": lab, "hex": "#000000"})]
        for n, lab in enumerate(labs)
    }  # fmt: skip
    p = run(items, attrs)
    assert len(p.attributes["accent"].clusters) == 2
    assert [t.key for t in p.tensions] == ["accent"]


def test_no_lens_and_empty_board() -> None:
    p = compute_profile([], {}, None, {})
    assert p.attributes == {} and p.centroid is None and p.signals == []
