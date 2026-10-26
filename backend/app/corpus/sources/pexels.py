"""Pexels API, a curated slice only: off unless PEXELS_ENABLED, at most 300 items."""

from collections.abc import Iterator

from app.corpus.sources.base import BaseSource, ManifestItem

API = "https://api.pexels.com/v1/search"
MAX_ITEMS = 300


class PexelsSource(BaseSource):
    name = "pexels"

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        s = self.settings
        if not (s.PEXELS_ENABLED and s.PEXELS_API_KEY):
            return
        limit = min(limit, MAX_ITEMS)
        page, seen = 1, 0
        while seen < limit:
            resp = self.client.get(
                API,
                params={"query": query, "per_page": min(80, limit - seen), "page": page},
                headers={"Authorization": s.PEXELS_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
            photos = data.get("photos") or []
            for p in photos:
                src = p.get("src") or {}
                url = src.get("large2x") or src.get("original")
                if not url or not p.get("id"):
                    continue
                who = (p.get("photographer") or "").strip() or None
                yield self._item(
                    str(p["id"]), landing_url=p.get("url") or url, image_url=url,
                    creator_name=who, license_code="Pexels",
                    license_url="https://www.pexels.com/license/",
                    attribution_text=f"Photo by {who or 'an unnamed photographer'} on Pexels",
                )  # fmt: skip
                seen += 1
                if seen >= limit:
                    return
            if not photos or not data.get("next_page"):
                return
            page += 1
