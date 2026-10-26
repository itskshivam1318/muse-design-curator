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


def test_defaults_are_mocks() -> None:
    s = Settings()
    assert get_reasoning(s).is_mock and get_segmentation(s).is_mock
    assert get_embedder(s).id == "mock"


def test_live_provider_without_key_is_misconfigured() -> None:
    for call, s in [
        (get_reasoning, Settings(REASONING_PROVIDER="muse_spark", MODEL_API_KEY=None)),
        (get_reasoning, Settings(REASONING_PROVIDER="muse_spark_open", BASETEN_API_KEY=None)),
        (get_segmentation, Settings(SEGMENTATION_PROVIDER="sam31", MODEL_API_KEY=None)),
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
        (get_reasoning, Settings(REASONING_PROVIDER="muse_spark", MODEL_API_KEY="k",
                                 MUSE_SPARK_MODEL="muse-spark-1.3-contributor")),
        (get_reasoning, Settings(REASONING_PROVIDER="muse_spark_open", BASETEN_API_KEY="k",
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
