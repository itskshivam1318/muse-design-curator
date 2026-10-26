from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.domain.lens import LensSpec, load_curated_lens, validate_lens

PARTS = [{"id": "p1", "sam_prompt": "main body"}]
ATTR = {"key": "a0", "label": "A", "category": "c", "kind": "boolean"}
BASE = {
    "id": "demo@1",
    "domain": "demo",
    "label": "Demo",
    "origin": "curated",
    "parts": PARTS,
    "attributes": [ATTR],
}


def make(**over) -> dict:  # type: ignore[no-untyped-def]
    d = deepcopy(BASE)
    d.update(over)
    return d


def shape_attr() -> dict:
    return {"key": "sh", "label": "S", "category": "c", "kind": "shape", "part": "p1"}


def test_shape_rejected_when_flag_off_accepted_when_on() -> None:
    lens = LensSpec.model_validate(make(attributes=[ATTR, shape_attr()]))
    with pytest.raises(ValueError):
        validate_lens(lens, shape_enabled=False)
    assert validate_lens(lens, shape_enabled=True) is lens


def test_lens_with_21_attributes_rejected() -> None:
    attrs = [{**ATTR, "key": f"a{i}"} for i in range(21)]
    with pytest.raises(ValidationError):
        LensSpec.model_validate(make(attributes=attrs))
    LensSpec.model_validate(make(attributes=attrs[:20]))


def test_more_than_8_parts_rejected() -> None:
    parts = [{"id": f"p{i}", "sam_prompt": "thing"} for i in range(9)]
    with pytest.raises(ValidationError):
        LensSpec.model_validate(make(parts=parts))


def test_undeclared_part_rejected() -> None:
    with pytest.raises(ValidationError):
        LensSpec.model_validate(make(attributes=[{**ATTR, "part": "nope"}]))


def test_duplicate_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        LensSpec.model_validate(make(attributes=[ATTR, ATTR]))


@pytest.mark.parametrize("prompt", ["a and b", "a, b", "a or b", "not a", "one two three four", ""])
def test_bad_sam_prompt_rejected(prompt: str) -> None:
    with pytest.raises(ValidationError):
        LensSpec.model_validate(make(parts=[{"id": "p1", "sam_prompt": prompt}]))


def test_part_ids_snake_case() -> None:
    with pytest.raises(ValidationError):
        LensSpec.model_validate(make(parts=[{"id": "Bad Id", "sam_prompt": "thing"}]))


@pytest.mark.parametrize("domain", ["watch", "fashion", "interior", "ui"])
def test_curated_lenses_validate(domain: str) -> None:
    on = load_curated_lens(domain, shape_enabled=True)
    off = load_curated_lens(domain, shape_enabled=False)
    assert on is not None and off is not None
    assert on.id == f"{domain}@1" and on.origin == "curated"
    assert any(a.kind == "shape" for a in on.attributes) == (domain != "ui")
    assert not any(a.kind == "shape" for a in off.attributes)


def test_unknown_or_unsafe_domain_returns_none() -> None:
    assert load_curated_lens("nonexistent", True) is None
    assert load_curated_lens("../x", True) is None
