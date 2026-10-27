"""Cleveland Museum of Art Open Access API (cc0=1; no key)."""

from collections.abc import Iterator
from typing import Any

from app.corpus.sources.base import BaseSource, ManifestItem

API = "https://openaccess-api.clevelandart.org/api/artworks/"
PAGE = 100


class ClevelandSource(BaseSource):
    name = "cleveland"

    def _from_row(self, row: dict[str, Any]) -> ManifestItem | None:
        image = (((row.get("images") or {}).get("web")) or {}).get("url")
        if row.get("share_license_status") != "CC0" or not image or row.get("id") is None:
            return None
        creators = row.get("creators") or []
        creator = (creators[0].get("description") or "").strip() or None if creators else None
        title = row.get("title") or "Untitled"
        by = f"{creator}, " if creator else ""
        return self._item(
            str(row["id"]),
            landing_url=row.get("url") or f"https://clevelandart.org/art/{row.get('accession_number')}",
            image_url=image, creator_name=creator, license_code="CC0-1.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            attribution_text=f"{by}{title}. Cleveland Museum of Art, Open Access (CC0)",
        )  # fmt: skip

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        skip, seen = 0, 0
        while seen < limit:
            resp = self.client.get(
                API,
                params={
                    "q": query, "cc0": 1, "has_image": 1, "skip": skip,
                    "limit": min(PAGE, max(limit - seen, 1)),
                },
            )  # fmt: skip
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data") or []
            for row in rows:
                item = self._from_row(row)
                if item is not None:
                    yield item
                    seen += 1
                    if seen >= limit:
                        return
            skip += len(rows)
            if not rows or skip >= int((data.get("info") or {}).get("total") or 0):
                return
