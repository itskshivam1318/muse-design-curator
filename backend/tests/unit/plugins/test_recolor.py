"""Variation · Color: label map, adjacency, assignments and the Lab recolour (pure numpy)."""

from itertools import combinations

import numpy as np
import pytest

from app.plugins.manifest import load_manifest
from app.plugins.registry import BUILTIN_DIR, load_builtin_module
from app.plugins.runners import check_params

rc = load_builtin_module("recolor", "recolor")


def box(h: int, w: int, y1: int, y2: int, x1: int, x2: int) -> np.ndarray:
    m = np.zeros((h, w), bool)
    m[y1:y2, x1:x2] = True
    return m


def test_label_map_smallest_wins() -> None:
    upper = box(40, 60, 5, 35, 5, 55)
    laces = box(40, 60, 10, 20, 20, 40)
    labels = rc.label_map([upper, laces])
    assert (labels[laces] == 1).all()
    assert (labels[upper & ~laces] == 0).all()
    assert (labels[~upper] == -1).all()
    # order does not matter: the smaller mask still wins
    labels = rc.label_map([laces, upper])
    assert (labels[laces] == 0).all() and (labels[upper & ~laces] == 1).all()


def test_adjacency_detects_touching_and_not_far() -> None:
    a = box(50, 90, 10, 40, 0, 30)
    b = box(50, 90, 10, 40, 30, 50)  # shares an edge with a
    c = box(50, 90, 10, 40, 75, 90)  # 25 px away from b
    labels = rc.label_map([a, b, c])
    assert rc.adjacency(labels, 3) == {(0, 1)}


def proper(assignment: tuple[int, ...], touching: set[tuple[int, int]]) -> bool:
    return all(assignment[i] != assignment[j] for i, j in touching)


def test_assignments_distinct_and_deterministic() -> None:
    touching = {(0, 1), (1, 2), (2, 3), (0, 3)}
    first = rc.assignments(4, 5, touching, 24, seed=1)
    assert first == rc.assignments(4, 5, touching, 24, seed=1)
    assert first[0] != rc.assignments(4, 5, touching, 24, seed=2)[0]
    assert len(first) == 24 and len(set(first)) == 24
    assert all(len(a) == 4 and all(0 <= c < 5 for c in a) for a in first)
    assert all(proper(a, touching) for a in first)


def test_assignments_large_space_is_sampled_and_proper() -> None:
    touching = {(i, j) for i, j in combinations(range(8), 2) if j == i + 1}
    out = rc.assignments(8, 8, touching, 24, seed=7)
    assert len(set(out)) == 24 and all(proper(a, touching) for a in out)
    assert out == rc.assignments(8, 8, touching, 24, seed=7)


def test_assignments_returns_fewer_when_exhausted() -> None:
    out = rc.assignments(2, 2, {(0, 1)}, 8, seed=1)
    assert sorted(out) == [(0, 1), (1, 0)]


def test_assignments_too_few_colours_fewest_repeats_first() -> None:
    touching = {(0, 1), (1, 2), (0, 2)}  # a triangle cannot be 2-coloured
    out = rc.assignments(3, 2, touching, 8, seed=1)
    repeats = [sum(a[i] == a[j] for i, j in touching) for a in out]
    assert repeats == sorted(repeats) and repeats[0] == 1 and len(set(out)) == len(out)


def test_recolor_keeps_outside_pixels_and_detail() -> None:
    rng = np.random.default_rng(0)
    rgb = np.clip(rng.normal(120, 18, (60, 80, 3)), 0, 255).astype(np.uint8)
    upper = box(60, 80, 10, 50, 10, 40)
    sole = box(60, 80, 10, 50, 40, 70)
    labels = rc.label_map([upper, sole])
    out = rc.recolor(rgb, labels, {0: "#f6a04d", 1: "#2a9d8f"})
    assert out.shape == rgb.shape and out.dtype == np.uint8
    assert (out[labels == -1] == rgb[labels == -1]).all()
    inner = box(60, 80, 14, 46, 14, 36)  # away from the feathered edges
    src_l, out_l = rc.rgb_to_lab(rgb)[..., 0][inner], rc.rgb_to_lab(out)[..., 0][inner]
    assert abs(out_l.std() - src_l.std()) <= 0.1 * src_l.std()
    target = rc.hex_to_lab("#f6a04d")
    got = rc.rgb_to_lab(out)[inner].mean(axis=0)
    assert np.hypot(got[1] - target[1], got[2] - target[2]) < 8


def test_params_schema_defaults_are_runnable() -> None:
    d = BUILTIN_DIR / "recolor"
    m = load_manifest(d, builtin=True)
    params = check_params(m, {})
    assert params["mode"] == "auto" and params["count"] == 8 and params["seed"] == 1
    assert params["palette"]["name"] == "Coral Bay" and 2 <= len(params["palette"]["colors"]) <= 8
    presets = m.params["properties"]["palette"]["x-presets"]
    assert len(presets) >= 10 and "Coral Bay" in {p["name"] for p in presets}
    assert m.needs == ["parts"] and m.outputs == ["images"]


def test_thin_parts_are_fully_recoloured() -> None:
    """A 2 px lace, against the background and lying on a coloured upper, takes its colour."""
    rng = np.random.default_rng(1)
    rgb = np.clip(rng.normal(120, 12, (60, 80, 3)), 0, 255).astype(np.uint8)
    upper = box(60, 80, 10, 50, 10, 50)
    lace_on_upper = box(60, 80, 20, 40, 29, 31)
    lace_alone = box(60, 80, 20, 40, 65, 67)  # only background around it
    labels = rc.label_map([upper, lace_on_upper, lace_alone])
    out = rc.recolor(rgb, labels, {0: "#264653", 1: "#f6a04d", 2: "#f6a04d"})
    target = rc.hex_to_lab("#f6a04d")
    lab = rc.rgb_to_lab(out)
    for lace in (lace_on_upper, lace_alone):
        got = lab[lace]
        de = np.hypot(got[:, 1] - target[1], got[:, 2] - target[2])
        assert de.max() < 8, de.max()
    # the seam is feathered on the larger part's side, and the background is untouched
    assert (out[labels == -1] == rgb[labels == -1]).all()
    beside = lab[30, 28]  # upper pixel next to the lace: part-way to the lace colour
    upper_target = rc.hex_to_lab("#264653")
    assert abs(beside[2] - upper_target[2]) > 3


def test_palette_colours_are_normalised_and_deduped() -> None:
    name, colors = rc.parse_palette({"name": "X", "colors": ["#ABC", "#aabbcc", "#112233"]})
    assert (name, colors) == ("X", ["#aabbcc", "#112233"])
    with pytest.raises(ValueError, match="different"):
        rc.parse_palette({"name": "X", "colors": ["#fff", "#FFFFFF"]})
