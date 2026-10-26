"""Append a source's licensed items to corpus/manifests/<domain>.jsonl (de-duplicated by id).

    uv run python scripts/import_corpus.py --domain watch --source commons \
        --query "wristwatch dial" --limit 200
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT, get_settings
from app.corpus.sources import SOURCES
from app.corpus.sources.base import ManifestItem
from app.corpus.sources.self_capture import SelfCaptureSource

DEFAULT_DIR = REPO_ROOT / "corpus" / "manifests"


def append_items(manifest: Path, items: list[ManifestItem]) -> int:
    """Append items whose id is not already in the manifest; returns how many were new."""
    manifest.parent.mkdir(parents=True, exist_ok=True)
    have: set[str] = set()
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                have.add(json.loads(line)["id"])
    new = []
    for item in items:
        if item.id not in have:
            have.add(item.id)
            new.append(item)
    if new:
        with manifest.open("a", encoding="utf-8") as f:
            for item in new:
                f.write(json.dumps(item.model_dump(), ensure_ascii=False) + "\n")
    return len(new)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", required=True)
    ap.add_argument("--source", required=True, choices=sorted(SOURCES))
    ap.add_argument("--query", default="")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--manifest-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--input", type=Path, help="self_capture only: the hand-written manifest")
    args = ap.parse_args(argv)
    source = SOURCES[args.source](args.domain, get_settings())
    if isinstance(source, SelfCaptureSource):
        source.manifest = args.input
    items = list(source.search(args.query, args.limit))
    added = append_items(args.manifest_dir / f"{args.domain}.jsonl", items)
    print(f"{args.source}: {len(items)} licensed items found, {added} new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
