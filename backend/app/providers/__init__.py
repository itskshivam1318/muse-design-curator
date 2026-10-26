"""Provider factories. Live providers fail loudly when misconfigured: no silent mock fallback."""

from __future__ import annotations

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

__all__ = ["ModelError", "get_embedder", "get_reasoning", "get_segmentation"]


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


def get_embedder(settings: Settings) -> Embedder:
    name = settings.EMBEDDER.replace("_", "-").replace("pe-core", "pe-core")
    if name == "mock":
        return MockEmbedder()
    if name == "siglip2":
        return SigLIP2Embedder()
    if name == "pe-core":
        return PECoreEmbedder()
    raise ModelError("PROVIDER_MISCONFIGURED", message=f"unknown EMBEDDER {name!r}")
