from app.domain.lens import LensSpec
from app.providers.reasoning import MockReasoningProvider


def _spec(raw: dict) -> LensSpec:  # type: ignore[type-arg]
    return LensSpec.model_validate({**raw, "id": "custom@1", "domain": "custom", "origin": "proposed"})


def test_mock_proposal_is_a_valid_generic_lens() -> None:
    p = MockReasoningProvider()
    raw = p.propose_lens([b"x"], "ctx", LensSpec.model_json_schema())
    assert raw == p.propose_lens([b"y"], "other", LensSpec.model_json_schema())  # deterministic
    spec = _spec(raw)
    assert [(x.id, x.grounding) for x in spec.parts] == [
        ("object", "sam"),
        ("background", "whole_image"),
    ]
    by = {a.key: a for a in spec.attributes}
    assert list(by) == ["primary_color", "material", "form", "finish", "density", "has_pattern", "style"]
    assert by["primary_color"].kind == "color" and by["primary_color"].part == "object"
    assert by["material"].kind == "enum" and by["material"].open_vocabulary  # type: ignore[union-attr]
    assert by["form"].kind == "enum" and by["form"].open_vocabulary  # type: ignore[union-attr]
    assert by["finish"].scale == ["matte", "satin", "gloss"]  # type: ignore[union-attr]
    assert by["density"].scale == ["sparse", "balanced", "dense"]  # type: ignore[union-attr]
    assert by["has_pattern"].kind == "boolean" and by["style"].kind == "text"
