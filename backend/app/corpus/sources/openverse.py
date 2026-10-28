"""Openverse image search (official API, BY / BY-SA / CC0 / PDM only)."""

import threading
import time
from collections.abc import Iterator
from typing import Any

from app.corpus.sources.base import BaseSource, ManifestItem
from app.corpus.sources.licenses import spdx_from_url

API = "https://api.openverse.org/v1"
# the API answers page_size above these with 401, and never pages past 240 results
PAGE_SIZE_ANON, PAGE_SIZE_AUTH, MAX_DEPTH = 20, 50, 240
TOKEN_MARGIN_S = 300

# client_id -> (access token, monotonic expiry); tokens live 12 h, so one serves many searches
_tokens: dict[str, tuple[str, float]] = {}
_tokens_lock = threading.Lock()


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

    def _token(self, fresh: bool = False) -> dict[str, str]:
        s = self.settings
        if not (s.OPENVERSE_CLIENT_ID and s.OPENVERSE_CLIENT_SECRET):
            return {}
        with _tokens_lock:
            cached = _tokens.get(s.OPENVERSE_CLIENT_ID)
        if cached and not fresh and time.monotonic() < cached[1]:
            return {"Authorization": f"Bearer {cached[0]}"}
        resp = self.client.post(
            f"{API}/auth_tokens/token/",
            data={
                "grant_type": "client_credentials", "client_id": s.OPENVERSE_CLIENT_ID,
                "client_secret": s.OPENVERSE_CLIENT_SECRET,
            },
        )  # fmt: skip
        resp.raise_for_status()
        body = resp.json()
        ttl = float(body.get("expires_in") or 3600)
        with _tokens_lock:
            _tokens[s.OPENVERSE_CLIENT_ID] = (
                body["access_token"], time.monotonic() + max(ttl - TOKEN_MARGIN_S, 60),
            )  # fmt: skip
        return {"Authorization": f"Bearer {body['access_token']}"}

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        headers = self._token()
        page_size = PAGE_SIZE_AUTH if headers else PAGE_SIZE_ANON
        page, seen, retried = 1, 0, False
        while seen < limit:
            size = min(page_size, max(limit - seen, 1))
            if (page - 1) * size >= MAX_DEPTH:
                return
            resp = self.client.get(
                f"{API}/images/",
                params={
                    "q": query, "license": "by,by-sa,cc0,pdm", "page": page, "page_size": size,
                    # dead-link checking costs up to 0.8 s per result; the indexer's download
                    # catches dead links anyway
                    "filter_dead": "false",
                },
                headers=headers,
            )  # fmt: skip
            if resp.status_code == 401 and headers and not retried:  # token expired or revoked
                headers, retried = self._token(fresh=True), True
                continue
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
