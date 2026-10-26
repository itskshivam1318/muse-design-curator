import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain.kinds import AttributeSpec

adapter = TypeAdapter(AttributeSpec)
BASE = {"key": "k_one", "label": "K", "category": "c"}

VALID = [
    {"kind": "enum", "vocabulary": ["a", "b"]},
    {"kind": "ordinal", "scale": ["low", "mid", "high"]},
    {"kind": "number", "unit": "mm", "min": 1, "max": 5, "tolerance": 0.5},
    {"kind": "boolean"},
    {"kind": "color"},
    {"kind": "text", "hint": "free"},
    {"kind": "shape", "part": "p1", "experimental": True},
]


@pytest.mark.parametrize("extra", VALID, ids=[v["kind"] for v in VALID])
def test_each_kind_validates_its_own_fields(extra: dict) -> None:
    spec = adapter.validate_python({**BASE, **extra})
    assert spec.kind == extra["kind"]


def test_enum_without_vocabulary_and_not_open_is_invalid() -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python({**BASE, "kind": "enum"})
    assert adapter.validate_python({**BASE, "kind": "enum", "open_vocabulary": True})


def test_ordinal_scale_bounds() -> None:
    for scale in (["a", "b"], list("abcdefgh"), ["a", "a", "b"]):
        with pytest.raises(ValidationError):
            adapter.validate_python({**BASE, "kind": "ordinal", "scale": scale})


def test_number_requires_positive_tolerance_and_sane_range() -> None:
    n = {**BASE, "kind": "number", "unit": "mm", "min": 1, "max": 5}
    with pytest.raises(ValidationError):
        adapter.validate_python({**n, "tolerance": 0})
    with pytest.raises(ValidationError):
        adapter.validate_python({**n, "tolerance": 1, "min": 5, "max": 1})


def test_shape_requires_part_and_experimental() -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python({**BASE, "kind": "shape", "experimental": True})
    with pytest.raises(ValidationError):
        adapter.validate_python({**BASE, "kind": "shape", "part": "p", "experimental": False})


def test_key_must_be_snake_case() -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python({**BASE, "key": "Bad Key", "kind": "boolean"})
