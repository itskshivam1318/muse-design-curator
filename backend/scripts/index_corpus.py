"""Index a domain's corpus manifest: hashes, masks, attributes and embeddings.

uv run python scripts/index_corpus.py --domain watch [--manifest path]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.corpus.indexer import index_corpus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", required=True)
    ap.add_argument("--manifest", type=Path, help="default: corpus/manifests/<domain>.jsonl")
    args = ap.parse_args(argv)
    manifest = args.manifest or REPO_ROOT / "corpus" / "manifests" / f"{args.domain}.jsonl"
    if not manifest.is_file():
        print(f"no manifest at {manifest}", file=sys.stderr)
        return 1
    from app.api import deps

    session = deps.new_session()
    try:
        report = index_corpus(session, args.domain, manifest)
    finally:
        session.close()
    print(
        f"indexed {report.indexed}, unchanged {report.skipped}, failed {report.failed}, "
        f"invalid provenance {report.invalid}, duplicates {report.duplicates}"
    )
    for item_id, why in report.reasons.items():
        print(f"  {item_id}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
