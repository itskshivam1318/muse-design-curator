import io
import sys

import numpy as np
import pytest
from PIL import Image

from app.config import Settings
from app.providers import get_embedder, get_reasoning, get_segmentation
from app.providers.embedding import MockEmbedder
from app.providers.reasoning import MockReasoningProvider
from app.providers.reliability import ModelError
from app.providers.segmentation import MockSegmentationProvider

SCHEMA = {
    "type": "object",
    "properties": {
        "tone": {"type": "string", "enum": ["warm", "cool", "neutral"]},
        "weight": {"type": "integer", "minimum": 1, "maximum": 5},
        "sharp": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["tone", "weight", "sharp", "confidence"],
}


def png(color: tuple[int, int, int], w: int = 90, h: int = 70) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def test_mock_reasoning_deterministic_and_flagged() -> None:
    p = MockReasoningProvider()
    assert p.is_mock is True
    a = p.extract([b"x"], SCHEMA, "p")
    assert a == p.extract([b"x"], SCHEMA, "p")
    assert a["tone"] in SCHEMA["properties"]["tone"]["enum"]  # type: ignore[index]
    assert 1 <= a["weight"] <= 5 and isinstance(a["sharp"], bool)
    assert 0.45 <= a["confidence"] <= 0.65
    assert p.extract([b"y"], SCHEMA, "p") != a or p.extract([b"z"], SCHEMA, "q") != a


def test_mock_reasoning_truth_map() -> None:
    p = MockReasoningProvider(truth={"tone": "cool"})
    assert p.propose_lens([b"x"], "ctx", SCHEMA)["tone"] == "cool"
    assert p.verify([b"x"], SCHEMA, "p")["tone"] == "cool"


def test_mock_segmentation_centre_box() -> None:
    p = MockSegmentationProvider()
    assert p.is_mock is True
    r = p.localize(png((1, 2, 3), 100, 50), "s", "thing")
    assert r.found and len(r.instances) == 1
    i = r.instances[0]
    assert i.bbox == (20, 10, 80, 40)
    assert i.mask.shape == (50, 100) and i.mask.sum() == 60 * 30
    assert np.array_equal(
        i.mask, p.localize(png((1, 2, 3), 100, 50), "s", "thing").instances[0].mask
    )


def test_mock_embedder_normalised_dim64() -> None:
    e = MockEmbedder()
    v = e.embed_images([png((255, 0, 0)), png((0, 0, 255))])
    assert v.shape == (2, 64) and e.dim == 64
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0)
    assert not np.allclose(v[0], v[1])
    t = e.embed_text(["a", "b"])
    assert t.shape == (2, 64) and np.allclose(np.linalg.norm(t, axis=1), 1.0)
    assert np.array_equal(v, e.embed_images([png((255, 0, 0)), png((0, 0, 255))]))


def test_code_defaults_are_live() -> None:
    f = Settings.model_fields
    assert f["REASONING_PROVIDER"].default == "muse-spark"
    assert f["SEGMENTATION_PROVIDER"].default == "sam-3.1"
    assert f["EMBEDDER"].default == "siglip2"


def test_test_environment_is_mock() -> None:
    s = Settings()
    assert get_reasoning(s).is_mock and get_segmentation(s).is_mock
    assert get_embedder(s).id == "mock"


def test_live_provider_without_key_is_misconfigured() -> None:
    for call, s in [
        (get_reasoning, Settings(REASONING_PROVIDER="muse-spark", MODEL_API_KEY=None)),
        (get_reasoning, Settings(REASONING_PROVIDER="muse-spark-open", BASETEN_API_KEY=None)),
        (get_segmentation, Settings(SEGMENTATION_PROVIDER="sam-3.1", MODEL_API_KEY=None)),
    ]:
        with pytest.raises(ModelError) as ei:
            call(s)
        assert ei.value.code == "PROVIDER_MISCONFIGURED"


def test_unknown_provider_name_is_misconfigured() -> None:
    with pytest.raises(ModelError) as ei:
        get_reasoning(Settings(REASONING_PROVIDER="nope"))
    assert ei.value.code == "PROVIDER_MISCONFIGURED"


def test_contributor_model_id_rejected() -> None:
    for call, s in [
        (get_reasoning, Settings(REASONING_PROVIDER="muse-spark", MODEL_API_KEY="k",
                                 MUSE_SPARK_MODEL="muse-spark-1.3-contributor")),
        (get_reasoning, Settings(REASONING_PROVIDER="muse-spark-open", BASETEN_API_KEY="k",
                                 BASETEN_MODEL="x-contributor")),
        (get_reasoning, Settings(MUSE_SPARK_MODEL="a-contributor")),
    ]:  # fmt: skip
        with pytest.raises(ModelError) as ei:
            call(s)
        assert ei.value.code == "PROVIDER_MISCONFIGURED"


def test_siglip2_without_extra_is_misconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)  # makes `import torch` raise ImportError
    with pytest.raises(ModelError) as ei:
        get_embedder(Settings(EMBEDDER="siglip2"))
    assert ei.value.code == "PROVIDER_MISCONFIGURED"
    assert "embed" in str(ei.value)


def test_documented_selector_values_build_live_providers() -> None:
    r = get_reasoning(Settings(REASONING_PROVIDER="muse-spark", MODEL_API_KEY="k"))
    assert r.id == "muse_spark" and not r.is_mock
    o = get_reasoning(Settings(REASONING_PROVIDER="muse-spark-open", BASETEN_API_KEY="k"))
    assert o.id == "muse_spark_open"
    seg = get_segmentation(Settings(SEGMENTATION_PROVIDER="sam-3.1", MODEL_API_KEY="k"))
    assert seg.id == "sam31" and not seg.is_mock
    # underscore aliases are accepted too
    assert (
        get_reasoning(Settings(REASONING_PROVIDER="muse_spark", MODEL_API_KEY="k")).id
        == "muse_spark"
    )


def test_pe_core_selector_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(ModelError) as ei:
        get_embedder(Settings(EMBEDDER="pe-core"))
    assert ei.value.code == "PROVIDER_MISCONFIGURED" and "embed" in str(ei.value)


def test_siglip_features_unwrap_model_output() -> None:
    from types import SimpleNamespace

    import torch

    from app.providers.embedding import _features

    t = torch.ones(1, 3)
    assert _features(t) is t
    assert _features(SimpleNamespace(pooler_output=t)) is t


def test_extraction_schema_is_strict_closed_objects() -> None:
    from app.domain.lens import load_curated_lens
    from app.extraction.schema import build_extraction_schema

    lens = load_curated_lens("watch", False)
    assert lens is not None

    def objects(node: object) -> list[dict]:  # type: ignore[type-arg]
        out: list[dict] = []  # type: ignore[type-arg]
        if isinstance(node, dict):
            if node.get("type") == "object":
                out.append(node)
            for v in node.values():
                out += objects(v)
        elif isinstance(node, list):
            for v in node:
                out += objects(v)
        return out

    found = objects(build_extraction_schema(lens))
    assert len(found) > 2
    for o in found:
        assert o.get("additionalProperties") is False
        assert set(o["required"]) == set(o["properties"])


def test_sam_input_is_shrunk_and_instances_map_back() -> None:
    import numpy as np

    from app.providers.segmentation import SegInstance, _rescale, shrink_for_api

    small_png = png((9, 9, 9))
    assert shrink_for_api(small_png)[0] is small_png
    big = io.BytesIO()
    Image.new("RGB", (2048, 1024), (5, 5, 5)).save(big, "JPEG")
    data, size = shrink_for_api(big.getvalue())
    assert size == (1024, 512) and Image.open(io.BytesIO(data)).size == (1024, 512)
    mask = np.zeros((512, 1024), dtype=bool)
    mask[100:200, 200:400] = True
    out = _rescale(SegInstance((200, 100, 400, 200), mask, 0.9), (1024, 512), (2048, 1024))
    assert out.mask.shape == (1024, 2048) and out.bbox == (400, 200, 800, 400)
    assert out.mask[300, 600] and not out.mask[10, 10] and out.score == 0.9
