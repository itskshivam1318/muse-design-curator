"""Provider factories. Live providers fail loudly when misconfigured: no silent mock fallback."""

from __future__ import annotations

import threading

from app.config import Settings
from app.providers.embedding import Embedder, MockEmbedder, PECoreEmbedder, SigLIP2Embedder
from app.providers.meta_client import check_model_id, get_client
from app.providers.reasoning import (
    MockReasoningProvider,
    MuseSparkOpenProvider,
    MuseSparkProvider,
    ReasoningProvider,
)
from app.providers.reliability import ModelError
from app.providers.segmentation import MockSegmentationProvider, Sam31Provider, SegmentationProvider

__all__ = ["ModelError", "embedder_id", "get_embedder", "get_reasoning", "get_segmentation"]


def _need(value: str | None, name: str, who: str) -> str:
    if not value:
        raise ModelError("PROVIDER_MISCONFIGURED", message=f"{who} requires {name} to be set")
    return value


def get_reasoning(settings: Settings) -> ReasoningProvider:
    check_model_id(settings.MUSE_SPARK_MODEL)
    check_model_id(settings.BASETEN_MODEL)
    name = settings.REASONING_PROVIDER.replace("_", "-")
    if name == "mock":
        return MockReasoningProvider()
    if name == "muse-spark":
        _need(settings.MODEL_API_KEY, "MODEL_API_KEY", "REASONING_PROVIDER=muse-spark")
        return MuseSparkProvider(
            get_client(settings), settings.MUSE_SPARK_MODEL,
            max_retries=settings.MODEL_MAX_RETRIES, timeout=settings.MODEL_TIMEOUT_S,
        )  # fmt: skip
    if name == "muse-spark-open":
        key = _need(
            settings.BASETEN_API_KEY, "BASETEN_API_KEY", "REASONING_PROVIDER=muse-spark-open"
        )
        return MuseSparkOpenProvider(
            api_key=key, model=settings.BASETEN_MODEL,
            max_retries=settings.MODEL_MAX_RETRIES, timeout=settings.MODEL_TIMEOUT_S,
        )  # fmt: skip
    raise ModelError("PROVIDER_MISCONFIGURED", message=f"unknown REASONING_PROVIDER {name!r}")


def get_segmentation(settings: Settings) -> SegmentationProvider:
    name = settings.SEGMENTATION_PROVIDER.replace("_", "-").replace("sam-3.1", "sam-3.1")
    if name == "mock":
        return MockSegmentationProvider()
    if name == "sam-3.1":
        _need(settings.MODEL_API_KEY, "MODEL_API_KEY", "SEGMENTATION_PROVIDER=sam-3.1")
        return Sam31Provider(
            get_client(settings), max_retries=settings.MODEL_MAX_RETRIES,
            timeout=settings.MODEL_TIMEOUT_S,
        )  # fmt: skip
    raise ModelError("PROVIDER_MISCONFIGURED", message=f"unknown SEGMENTATION_PROVIDER {name!r}")


# One loaded embedder per process and name: loading SigLIP 2 takes seconds and ~1.5 GB.
_embedders: dict[str, Embedder] = {}
_embedders_lock = threading.Lock()


def _load_embedder(name: str) -> Embedder:
    if name == "mock":
        return MockEmbedder()
    if name == "siglip2":
        return SigLIP2Embedder()
    if name == "pe-core":
        return PECoreEmbedder()
    raise ModelError("PROVIDER_MISCONFIGURED", message=f"unknown EMBEDDER {name!r}")


def get_embedder(settings: Settings) -> Embedder:
    """The process-wide embedder for settings.EMBEDDER, loaded once (thread-safe, lazy). A failed
    load is not cached, so fixing the environment and retrying works."""
    name = settings.EMBEDDER.replace("_", "-")
    cached = _embedders.get(name)
    if cached is not None:
        return cached
    with _embedders_lock:
        if name not in _embedders:
            _embedders[name] = _load_embedder(name)
        return _embedders[name]


def embedder_id(settings: Settings) -> str:
    """The configured embedder's id without loading its weights."""
    name = settings.EMBEDDER.replace("_", "-")
    classes: dict[str, type[Embedder]] = {
        "mock": MockEmbedder, "siglip2": SigLIP2Embedder, "pe-core": PECoreEmbedder,
    }  # fmt: skip
    if name not in classes:
        raise ModelError("PROVIDER_MISCONFIGURED", message=f"unknown EMBEDDER {name!r}")
    return str(classes[name].id)
