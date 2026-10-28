"""Wikimedia Commons via the MediaWiki Action API (imageinfo + extmetadata)."""

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from app.config import Settings
from app.corpus.sources.base import BaseSource, ManifestItem, Throttle, strip_html
from app.corpus.sources.licenses import spdx_from_text
from app.domain.lens import curated_depicts

API = "https://commons.wikimedia.org/w/api.php"
MIN_INTERVAL_S = 60 / 200  # Wikimedia allows 200 requests/min with a descriptive User-Agent
PAGE_SIZE = 50


def _meta(info: dict[str, Any], key: str) -> str | None:
    value = (info.get("extmetadata") or {}).get(key)
    return value.get("value") if isinstance(value, dict) else None


class CommonsSource(BaseSource):
    name = "commons"

    def __init__(
        self,
        domain: str,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(domain, settings, client, sleep)
        self._throttle = Throttle(MIN_INTERVAL_S, sleep)

    def _from_page(self, page: dict[str, Any]) -> ManifestItem | None:
        infos = page.get("imageinfo") or []
        if not infos:
            return None
        info = infos[0]
        code = spdx_from_text(_meta(info, "LicenseShortName"))
        if code is None:  # NC, ND or unrecognised: never imported
            return None
        url = info.get("thumburl") or info.get("url")
        if not url:
            return None
        title = str(page.get("title", "")).removeprefix("File:")
        creator = strip_html(_meta(info, "Artist"))
        short = strip_html(_meta(info, "LicenseShortName")) or code
        licence_url = _meta(info, "LicenseUrl")
        credit = f"{creator}, " if creator else ""
        return self._item(
            str(page["pageid"]),
            landing_url=info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{title}",
            image_url=url, creator_name=creator, license_code=code, license_url=licence_url,
            attribution_text=f'"{title}", {credit}{short}, via Wikimedia Commons',
        )  # fmt: skip

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        """Files tagged as depicting the domain's subject first (precise), then any file whose
        title or caption matches (broad); each file once."""
        seen: set[str] = set()
        qids = curated_depicts(self.domain)
        searches = [f"filetype:bitmap {query}"]
        if qids:
            tagged = "|".join(f"P180={q}" for q in qids)
            searches.insert(0, f"filetype:bitmap haswbstatement:{tagged} {query}")
        for gsr in searches:
            for item in self._search(gsr, limit - len(seen)):
                if item.id in seen:
                    continue
                seen.add(item.id)
                yield item
                if len(seen) >= limit:
                    return

    def _search(self, gsrsearch: str, limit: int) -> Iterator[ManifestItem]:
        params: dict[str, Any] = {
            "action": "query", "format": "json", "formatversion": 2, "generator": "search",
            "gsrsearch": gsrsearch, "gsrnamespace": 6,
            "gsrlimit": PAGE_SIZE, "prop": "imageinfo", "iiprop": "url|extmetadata|size",
            "iiurlwidth": 1600,
        }  # fmt: skip
        seen = 0
        while seen < limit:
            self._throttle.wait()
            resp = self.client.get(API, params=params)
            resp.raise_for_status()
            data = resp.json()
            pages = sorted(
                (data.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0)
            )
            for page in pages:
                item = self._from_page(page)
                if item is not None:
                    yield item
                    seen += 1
                    if seen >= limit:
                        return
            cont = data.get("continue")
            if not cont:
                return
            params = {**params, **cont}
