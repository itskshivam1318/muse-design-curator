"""Art Institute of Chicago public API (is_public_domain, CC0)."""

from collections.abc import Iterator

from app.corpus.sources.base import BaseSource, ManifestItem

API = "https://api.artic.edu/api/v1/artworks/search"
FIELDS = ["id", "title", "image_id", "artist_title", "is_public_domain"]
IIIF_FALLBACK = "https://www.artic.edu/iiif/2"


class AicSource(BaseSource):
    name = "aic"

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        page, seen = 1, 0
        while seen < limit:
            body = {
                "q": query, "fields": FIELDS, "limit": min(100, max(limit - seen, 1)),
                "page": page,
                "query": {"bool": {"filter": [{"term": {"is_public_domain": True}}]}},
            }  # fmt: skip
            resp = self.client.post(API, json=body)
            resp.raise_for_status()
            data = resp.json()
            iiif = (data.get("config") or {}).get("iiif_url") or IIIF_FALLBACK
            rows = data.get("data") or []
            for row in rows:
                if row.get("is_public_domain") is not True or not row.get("image_id"):
                    continue
                artist = (row.get("artist_title") or "").strip() or None
                title = row.get("title") or "Untitled"
                by = f"{artist}, " if artist else ""
                yield self._item(
                    str(row["id"]),
                    landing_url=f"https://www.artic.edu/artworks/{row['id']}",
                    image_url=f"{iiif}/{row['image_id']}/full/843,/0/default.jpg",
                    creator_name=artist, license_code="CC0-1.0",
                    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                    attribution_text=f"{by}{title}. Art Institute of Chicago, public domain (CC0)",
                )  # fmt: skip
                seen += 1
                if seen >= limit:
                    return
            pagination = data.get("pagination") or {}
            if not rows or page >= int(pagination.get("total_pages") or 1):
                return
            page += 1
