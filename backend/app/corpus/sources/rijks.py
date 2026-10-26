"""Rijksmuseum open data: id-only search, then one Linked Art document per object (N+1)."""

from collections.abc import Iterator
from typing import Any

from app.corpus.sources.base import BaseSource, ManifestItem
from app.corpus.sources.licenses import spdx_from_url

SEARCH = "https://data.rijksmuseum.nl/search/collection"
LINKED_ART = {"Accept": "application/ld+json"}
DELAY_S = 0.2


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _name(doc: dict[str, Any]) -> str:
    for n in doc.get("identified_by") or []:
        if n.get("type") == "Name" and n.get("content"):
            return str(n["content"])
    return str(doc.get("_label") or "Untitled")


def _maker(doc: dict[str, Any]) -> str | None:
    for who in (doc.get("produced_by") or {}).get("carried_out_by") or []:
        label = who.get("_label")
        if label:
            return str(label)
    return None


def _licence_url(doc: dict[str, Any]) -> str | None:
    for node in _walk(doc.get("subject_to") or doc.get("referred_to_by") or []):
        for key in ("id", "content", "_label"):
            val = node.get(key)
            if isinstance(val, str) and spdx_from_url(val):
                return val
    return None


def _image(doc: dict[str, Any]) -> str | None:
    for node in _walk(doc.get("representation") or doc.get("shows") or []):
        for point in node.get("access_point") or []:
            if isinstance(point, dict) and point.get("id"):
                return str(point["id"])
    return None


class RijksSource(BaseSource):
    name = "rijks"

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        resp = self.client.get(
            SEARCH, params={"title": query, "imageAvailable": "true"}, headers=LINKED_ART
        )
        resp.raise_for_status()
        seen = 0
        for ref in resp.json().get("orderedItems") or []:
            if seen >= limit:
                return
            url = ref.get("id") if isinstance(ref, dict) else None
            if not url:
                continue
            self._sleep(DELAY_S)
            r = self.client.get(url, headers=LINKED_ART)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            doc = r.json()
            licence_url, image = _licence_url(doc), _image(doc)
            code = spdx_from_url(licence_url)
            if code is None or not image:  # licence is per object: skip what we cannot verify
                continue
            maker = _maker(doc)
            by = f"{maker}, " if maker else ""
            source_id = url.rstrip("/").rsplit("/", 1)[-1]
            yield self._item(
                source_id, landing_url=url, image_url=image, creator_name=maker,
                license_code=code, license_url=licence_url,
                attribution_text=f"{by}{_name(doc)}. Rijksmuseum, {code}",
            )  # fmt: skip
            seen += 1
