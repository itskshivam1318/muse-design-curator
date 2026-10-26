from __future__ import annotations

import base64

import httpx2
import openai

from app.config import Settings
from app.providers.reliability import ModelError


def get_client(settings: Settings, http_client: httpx2.Client | None = None) -> openai.OpenAI:
    """Sync OpenAI-SDK client for Meta's Model API. Retries are owned by reliability.py."""
    return openai.OpenAI(
        base_url=settings.META_BASE_URL,
        api_key=settings.MODEL_API_KEY or "unset",
        timeout=settings.MODEL_TIMEOUT_S,
        max_retries=0,
        http_client=http_client,
    )


def check_model_id(model: str) -> str:
    if model.endswith("-contributor"):
        raise ModelError("PROVIDER_MISCONFIGURED", message=f"model {model!r} is not allowed")
    return model


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"


def data_url(data: bytes, mime: str | None = None) -> str:
    return f"data:{mime or sniff_mime(data)};base64,{base64.b64encode(data).decode()}"
