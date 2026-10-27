"""The Metropolitan Museum of Art Open Access API (CC0 where isPublicDomain is true)."""

from collections.abc import Iterator

from app.corpus.sources.base import BaseSource, ManifestItem

# search moved to v1.1 (v1/search was retired 2026-10-01); objects exist only under v1, and v1.1
# object requests 404, which repeated fast enough trips the museum's bot protection
SEARCH_API = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
OBJECTS_API = "https://collectionapi.metmuseum.org/public/collection/v1/objects"
DELAY_S = 0.4  # faster loops trip the museum's bot protection


class MetSource(BaseSource):
    name = "met"

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        resp = self.client.get(
            SEARCH_API, params={"q": query, "hasImages": "true", "isPublicDomain": "true"}
        )
        resp.raise_for_status()
        ids = resp.json().get("objectIDs") or []
        seen = 0
        for object_id in ids:
            if seen >= limit:
                return
            self._sleep(DELAY_S)
            r = self.client.get(f"{OBJECTS_API}/{object_id}")
            if r.status_code == 404:
                continue
            r.raise_for_status()
            obj = r.json()
            # the search endpoint ignores the public-domain filter, so check every object
            if obj.get("isPublicDomain") is not True or not obj.get("primaryImage"):
                continue
            artist = (obj.get("artistDisplayName") or "").strip() or None
            title = obj.get("title") or "Untitled"
            by = f"{artist}, " if artist else ""
            yield self._item(
                str(obj["objectID"]),
                landing_url=obj.get("objectURL")
                or f"https://www.metmuseum.org/art/collection/search/{obj['objectID']}",
                image_url=obj["primaryImage"], creator_name=artist, license_code="CC0-1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                attribution_text=f"{by}{title}. The Metropolitan Museum of Art, Open Access (CC0)",
            )  # fmt: skip
            seen += 1
