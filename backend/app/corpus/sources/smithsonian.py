"""Smithsonian Open Access: the search API when SMITHSONIAN_API_KEY is set, else the S3 bulk files.

The API (api.data.gov key, free) answers a keyword search across every Smithsonian museum in about
a second, so it is the live-search path. The bulk files need no key but are read shard by shard
(256 per unit), which suits a one-off corpus import, never a 20-second live search.
"""

import json
from collections.abc import Iterator
from typing import Any

from app.corpus.sources.base import BaseSource, ManifestItem

BUCKET = "https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan"
API = "https://api.si.edu/openaccess/api/v1.0/search"
API_ROWS = 100  # the API's page cap
DEFAULT_UNIT = "chndm"  # Cooper Hewitt
SHARDS = [f"{i:02x}" for i in range(256)]


def _creator(record: dict[str, Any]) -> str | None:
    names = ((record.get("content") or {}).get("freetext") or {}).get("name") or []
    for n in names:
        if n.get("content"):
            return str(n["content"]).strip() or None
    return None


class SmithsonianSource(BaseSource):
    name = "smithsonian"
    unit = DEFAULT_UNIT

    def _lines(self, shard_url: str) -> Iterator[str]:
        with self.client.stream("GET", shard_url) as resp:
            if resp.status_code == 404:
                return
            resp.raise_for_status()
            yield from resp.iter_lines()

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        if self.settings.SMITHSONIAN_API_KEY:
            yield from self._search_api(query, limit)
            return
        terms = query.lower().split()
        seen = 0
        for shard in SHARDS:
            for line in self._lines(f"{BUCKET}/{self.unit}/{shard}.txt"):
                if seen >= limit:
                    return
                if not line.strip():
                    continue
                low = line.lower()
                if not all(t in low for t in terms):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                item = self._from_record(rec, terms)
                if item is not None:
                    yield item
                    seen += 1
            if seen >= limit:
                return

    def _search_api(self, query: str, limit: int) -> Iterator[ManifestItem]:
        start, seen = 0, 0
        q = f"{query} AND online_media_type:Images AND media_usage:CC0"
        while seen < limit:
            resp = self.client.get(
                API,
                params={
                    "q": q, "start": start, "rows": min(API_ROWS, max(limit - seen, 1)),
                    "api_key": self.settings.SMITHSONIAN_API_KEY,
                },
            )  # fmt: skip
            resp.raise_for_status()
            body = resp.json().get("response") or {}
            rows = body.get("rows") or []
            for rec in rows:
                item = self._from_record(rec, [])  # the API already matched the query
                if item is not None:
                    yield item
                    seen += 1
                    if seen >= limit:
                        return
            start += len(rows)
            if not rows or start >= int(body.get("rowCount") or 0):
                return

    def _from_record(self, rec: dict[str, Any], terms: list[str]) -> ManifestItem | None:
        content = rec.get("content") or {}
        dnr = content.get("descriptiveNonRepeating") or {}
        title = (
            ((content.get("descriptiveNonRepeating") or {}).get("title") or {}).get("content")
            or rec.get("title")
            or ""
        )
        if terms and not all(t in str(title).lower() for t in terms):
            return None
        media = ((dnr.get("online_media") or {}).get("media")) or []
        for m in media:
            if (m.get("usage") or {}).get("access") != "CC0" or not m.get("content"):
                continue
            if m.get("type") and m["type"] != "Images":
                continue
            creator = _creator(rec)
            by = f"{creator}, " if creator else ""
            return self._item(
                # record_ID is stable across the bulk files and the API (whose row id is not)
                str(dnr.get("record_ID") or rec.get("id")).replace("edanmdm:", ""),
                landing_url=dnr.get("record_link") or m["content"], image_url=m["content"],
                creator_name=creator, license_code="CC0-1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                attribution_text=f"{by}{title or 'Untitled'}. Smithsonian Open Access (CC0)",
            )  # fmt: skip
        return None
