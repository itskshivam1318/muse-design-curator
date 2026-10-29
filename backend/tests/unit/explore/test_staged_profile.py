"""Staged takes stay out of the profile."""

from types import SimpleNamespace as NS
from typing import Any

from app.board.profile import compute_profile
from tests.unit.board.test_profile import LENS, attr


def item(i: str, staged: bool = False) -> Any:
    return NS(id=i, role="reference", embedding_json=None, kind="image", staged=staged)


def test_profile_ignores_staged_items() -> None:
    items = [item("a"), item("b"), item("c", staged=True), item("d", staged=True)]
    vals = ["brushed", "brushed", "polished", "polished"]
    attrs = {i.id: [attr("finish", v)] for i, v in zip(items, vals, strict=True)}
    p = compute_profile(items, attrs, LENS, {})
    assert p.n_reference == 2
    assert p.attributes["finish"].distribution == {"brushed": 2}
