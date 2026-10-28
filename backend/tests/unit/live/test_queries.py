import pytest
from pydantic import ValidationError

from app.domain.lens import load_curated_lens
from app.domain.variation import ProtectedSpec, VariationRequest, VariationSpec
from app.live import queries
from app.providers.reasoning import MockReasoningProvider


def make_spec(mode: str = "explore", values: tuple[str, ...] = ()) -> tuple[VariationSpec, object]:
    lens = load_curated_lens("watch", False)
    assert lens is not None
    attrs = {a.key: a for a in lens.attributes}
    req = VariationRequest(
        source_item_id="i", target_key="dial_color", mode=mode,  # type: ignore[arg-type]
        target_values=list(values), protected_keys=["case_shape"],
    )  # fmt: skip
    spec = VariationSpec(
        request=req, target_spec=attrs["dial_color"], target_value="black", values=values,
        protected=(ProtectedSpec(key="case_shape", spec=attrs["case_shape"], value="round"),),
    )  # fmt: skip
    return spec, lens


def test_mock_provider_returns_three_to_five_strings(session) -> None:  # type: ignore[no-untyped-def]
    spec, lens = make_spec()
    out = queries.write_queries(spec, {}, lens, "", MockReasoningProvider(), session=session)
    assert 3 <= len(out) <= 5 and all(isinstance(q, str) and q.strip() for q in out)
    again = queries.write_queries(spec, {}, lens, "", MockReasoningProvider(), session=session)
    assert out == again


def test_result_is_cached_and_prompt_names_target(session) -> None:  # type: ignore[no-untyped-def]
    spec, lens = make_spec()
    calls: list[str] = []

    class Counting(MockReasoningProvider):
        def extract(self, images, schema, prompt):  # type: ignore[no-untyped-def]
            calls.append(prompt)
            return super().extract(images, schema, prompt)

    p = Counting()
    queries.write_queries(spec, {}, lens, "", p, session=session)
    queries.write_queries(spec, {}, lens, "", p, session=session)
    assert len(calls) == 1
    assert "dial" in calls[0].lower() and "case" in calls[0].lower()
    assert queries.PROMPT_VERSION == "live-queries-v2"


def test_schema_rejects_other_shapes() -> None:
    for bad in (
        {"queries": ["a", "b"]}, {"queries": []}, {"queries": [1, 2, 3]},
        {"queries": ["a"] * 6}, {"q": ["a", "b", "c"]}, {"queries": ["a", "", "c"]},
    ):  # fmt: skip
        with pytest.raises(ValidationError):
            queries.QueriesOut.model_validate(bad)
    ok = queries.QueriesOut.model_validate({"queries": [" a ", "b", "c"]})
    assert ok.queries == ["a", "b", "c"]
    assert queries.QUERIES_SCHEMA["properties"]["queries"]["minItems"] == 3


def test_over_long_answer_is_trimmed_to_five(session) -> None:  # type: ignore[no-untyped-def]
    spec, lens = make_spec()

    class Many(MockReasoningProvider):
        def extract(self, images, schema, prompt):  # type: ignore[no-untyped-def]
            return {"queries": [f"q{i}" for i in range(8)]}

    assert queries.write_queries(spec, {}, lens, "", Many(), session=session) == [
        f"q{i}" for i in range(5)
    ]


def test_fallback_queries_name_target_and_protected() -> None:
    spec, lens = make_spec("prefer", ("red",))
    fb = queries.fallback_queries(spec, lens)
    assert 3 <= len(fb) <= 5
    assert any("red" in q for q in fb)


def test_broad_queries_name_the_target_part_and_target() -> None:
    spec, lens = make_spec()
    assert queries.broad_queries(spec, lens) == ["watch dial", "watch dial colour"]


def test_broad_queries_use_the_preferred_value() -> None:
    spec, lens = make_spec("prefer", ("dark_blue",))
    assert queries.broad_queries(spec, lens)[1] == "watch dark blue"


def test_with_broad_appends_only_new_queries() -> None:
    spec, lens = make_spec()
    assert queries.with_broad(["Watch Dial", "black dial pilot"], spec, lens) == [
        "Watch Dial", "black dial pilot", "watch dial colour",
    ]  # fmt: skip
