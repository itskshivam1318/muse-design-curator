"""Openverse image search (official API, BY / BY-SA / CC0 / PDM only)."""

from collections.abc import Iterator
from typing import Any

from app.corpus.sources.base import BaseSource, ManifestItem
from app.corpus.sources.licenses import spdx_from_url

API = "https://api.openverse.org/v1"


def _code(row: dict[str, Any]) -> str | None:
    kind = str(row.get("license", "")).lower()
    version = str(row.get("license_version") or "")
    if kind == "cc0":
        return "CC0-1.0"
    if kind == "pdm":
        return "PDM-1.0"
    if kind in ("by", "by-sa") and version:
        return f"CC-{kind.upper()}-{version}"
    return spdx_from_url(row.get("license_url"))


class OpenverseSource(BaseSource):
    name = "openverse"

    def _token(self) -> dict[str, str]:
        s = self.settings
        if not (s.OPENVERSE_CLIENT_ID and s.OPENVERSE_CLIENT_SECRET):
            return {}
        resp = self.client.post(
            f"{API}/auth_tokens/token/",
            data={
                "grant_type": "client_credentials", "client_id": s.OPENVERSE_CLIENT_ID,
                "client_secret": s.OPENVERSE_CLIENT_SECRET,
            },
        )  # fmt: skip
        resp.raise_for_status()
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        headers = self._token()
        page_size = 500 if headers else 20  # anonymous clients are capped at 20 per page
        page, seen = 1, 0
        while seen < limit:
            resp = self.client.get(
                f"{API}/images/",
                params={
                    "q": query, "license": "by,by-sa,cc0,pdm", "page": page,
                    "page_size": min(page_size, max(limit - seen, 1)),
                },
                headers=headers,
            )  # fmt: skip
            if resp.status_code == 400:  # past the last page
                return
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            for row in results:
                code, url = _code(row), row.get("url")
                if code is None or not url or not row.get("id"):
                    continue
                yield self._item(
                    str(row["id"]),
                    landing_url=row.get("foreign_landing_url") or url, image_url=url,
                    creator_name=row.get("creator") or None, license_code=code,
                    license_url=row.get("license_url"),
                    attribution_text=row.get("attribution")
                    or f'"{row.get("title") or "Untitled"}" ({code})',
                )  # fmt: skip
                seen += 1
                if seen >= limit:
                    return
            if not results or page >= int(data.get("page_count") or 1):
                return
            page += 1
