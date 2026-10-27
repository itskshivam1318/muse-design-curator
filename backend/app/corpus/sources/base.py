"""Shared pieces for source adapters. Adapters use official APIs or bulk files, never HTML pages."""

import html
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.config import Settings, get_settings


class ManifestItem(BaseModel):
    id: str
    domain: str
    source: str
    source_id: str
    landing_url: str
    image_url: str
    creator_name: str | None = None
    license_code: str
    license_url: str | None = None
    attribution_text: str
    fetched_at: str = Field(default_factory=lambda: now_iso())


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def item_id(source: str, source_id: str) -> str:
    return f"cx_{source}_{source_id}"


class Source(Protocol):
    name: str

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]: ...


def user_agent(settings: Settings) -> str:
    return f"DesignLanguageEngine/0.1 (contact: {settings.CONTACT_EMAIL or 'unset'})"


def source_headers(settings: Settings) -> dict[str, str]:
    """Headers for licensed-source APIs and image downloads.

    The Art Institute of Chicago's Cloudflare rules challenge (403) any API or IIIF request that
    lacks `AIC-User-Agent`; other hosts ignore it, and it repeats what User-Agent already says.
    """
    ua = user_agent(settings)
    return {"User-Agent": ua, "AIC-User-Agent": ua}


def strip_html(value: str | None) -> str | None:
    """Plain text of an HTML fragment (Commons credits arrive as HTML); None when empty."""
    if not value:
        return None
    text = HTMLParser(f"<div>{value}</div>").text(separator=" ")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text or None


class Throttle:
    """Keeps at least `interval` seconds between calls."""

    def __init__(
        self,
        interval: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval, self._sleep, self._clock = interval, sleep, clock
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self.interval:
            self._sleep(self.interval - (now - self._last))
            now = self._clock()
        self._last = now


class BaseSource:
    name = ""

    def __init__(
        self,
        domain: str,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.domain = domain
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(
            timeout=30, headers=source_headers(self.settings), follow_redirects=True
        )
        self._sleep = sleep

    def _item(self, source_id: str, **fields: str | None) -> ManifestItem:
        return ManifestItem(
            id=item_id(self.name, source_id), domain=self.domain, source=self.name,
            source_id=source_id, **fields,  # type: ignore[arg-type]
        )  # fmt: skip

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:  # pragma: no cover
        raise NotImplementedError
