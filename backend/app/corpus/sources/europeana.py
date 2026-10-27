"""Europeana Search API (reusability=open: CC0, PDM, CC BY, CC BY-SA; free self-serve key)."""

from collections.abc import Iterator
from typing import Any

from app.corpus.sources.base import BaseSource, ManifestItem
from app.corpus.sources.licenses import spdx_from_url

API = "https://api.europeana.eu/record/v2/search.json"
ROWS = 100  # the API's page cap
MAX_START = 1000  # start + rows may not pass 1000 (deeper needs cursor paging)


def _first(row: dict[str, Any], key: str) -> str | None:
    v = row.get(key)
    if isinstance(v, list):
        v = next((x for x in v if isinstance(x, str) and x.strip()), None)
    return v.strip() if isinstance(v, str) and v.strip() else None


class EuropeanaSource(BaseSource):
    name = "europeana"

    def _from_row(self, row: dict[str, Any]) -> ManifestItem | None:
        code = spdx_from_url(_first(row, "rights"))
        image = _first(row, "edmIsShownBy")
        rid = row.get("id")
        if code is None or not image or not isinstance(rid, str):  # every item states its rights
            return None
        title = (_first(row, "title") or "Untitled").split("\n")[0]
        creator = _first(row, "dcCreator")
        provider = _first(row, "dataProvider")
        by = ", ".join(x for x in (creator, provider) if x)
        return self._item(
            rid.strip("/").replace("/", "_"),
            landing_url=f"https://www.europeana.eu/item{rid}", image_url=image,
            creator_name=creator, license_code=code, license_url=_first(row, "rights"),
            attribution_text=f'"{title}"{", " + by if by else ""}, {code}, via Europeana',
        )  # fmt: skip

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        key = self.settings.EUROPEANA_API_KEY
        if not key:
            return
        start, seen = 1, 0
        while seen < limit and start <= MAX_START:
            rows = min(ROWS, max(limit - seen, 1), MAX_START - start + 1)
            resp = self.client.get(
                API,
                params={
                    "wskey": key, "query": query, "reusability": "open", "media": "true",
                    "qf": "TYPE:IMAGE", "profile": "standard", "rows": rows, "start": start,
                },
            )  # fmt: skip
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            for row in items:
                item = self._from_row(row)
                if item is not None:
                    yield item
                    seen += 1
                    if seen >= limit:
                        return
            start += len(items)
            if not items or start > int(data.get("totalResults") or 0):
                return
