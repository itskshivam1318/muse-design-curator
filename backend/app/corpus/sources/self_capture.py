"""Hand-written manifest of our own captures; every entry names its (SPDX) licence."""

import json
from collections.abc import Iterator
from pathlib import Path

from app.corpus.sources.base import BaseSource, ManifestItem, item_id


class SelfCaptureSource(BaseSource):
    name = "self_capture"
    manifest: Path | None = None

    def search(self, query: str, limit: int) -> Iterator[ManifestItem]:
        if self.manifest is None or not self.manifest.is_file():
            return
        q, seen = query.strip().lower(), 0
        for line in self.manifest.read_text(encoding="utf-8").splitlines():
            if seen >= limit:
                return
            if not line.strip():
                continue
            row = json.loads(line)
            if q and q not in line.lower():
                continue
            sid = str(row["source_id"])
            yield ManifestItem.model_validate(
                {**row, "id": item_id(self.name, sid), "source": self.name, "domain": self.domain}
            )
            seen += 1
