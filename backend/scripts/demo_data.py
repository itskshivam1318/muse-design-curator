"""Real-photo demo corpus: import manifests -> index with the live providers -> seed the boards.

    uv run python scripts/demo_data.py [--yes] [--plan] [--skip-import]

Without --yes only the plan is printed (no network, no model calls). Idempotent: manifests de-duplicate by id, indexing skips what is indexed, and every model call is
cached, so a re-run costs nothing. The caps below are hard limits and the planned call counts are
printed before any live model call. Only official source APIs and bulk files are used.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT, get_settings
from app.corpus.sources import SOURCES
from app.domain.lens import load_curated_lens

MANIFEST_DIR = REPO_ROOT / "corpus" / "manifests"
MAX_ITEMS, MAX_SPARK_CALLS, MAX_SAM_CALLS = 1200, 2400, 6000

# (domain, source, query, limit)
PLAN: list[tuple[str, str, str, int]] = [
    ("watch", "commons", "wristwatch dial", 200),
    ("watch", "commons", "chronograph watch", 150),
    ("watch", "commons", "dive watch", 100),
    ("watch", "aic", "watch", 40),
    ("fashion", "smithsonian", "costume", 60),
    ("fashion", "smithsonian", "textile", 60),
    ("fashion", "aic", "dress", 60),
    ("fashion", "commons", "streetwear", 60),
    ("interior", "met", "chair", 80),
    ("interior", "rijks", "stoel", 60),
    ("interior", "commons", "living room interior", 80),
    ("ui", "commons", "screenshot user interface", 80),
    ("ui", "commons", "dashboard screenshot", 60),
]
DOMAINS = ["watch", "fashion", "interior", "ui"]
# Live indexing is ~40 s per item (SAM parts and a Spark read, one after the other), so the demo
# indexes an evenly spaced subset of each manifest. Raise these (or run `make index`) for more.
INDEX_LIMIT = {"watch": 60, "fashion": 40, "interior": 40, "ui": 40}


def planned_calls(plan: list[tuple[str, str, str, int]] = PLAN) -> dict[str, int]:
    """Worst case: one Muse Spark call per item, one SAM call per SAM-grounded lens part."""
    settings = get_settings()
    items = sum(
        min(sum(lim for d, *_x, lim in plan if d == dom), INDEX_LIMIT[dom]) for dom in DOMAINS
    )
    spark = sam = 0
    for domain in DOMAINS:
        n = min(sum(limit for d, *_x, limit in plan if d == domain), INDEX_LIMIT[domain])
        lens = load_curated_lens(domain, settings.SHAPE_KIND_ENABLED)
        if lens is None:
            continue
        spark += n
        sam += n * sum(1 for p in lens.parts if p.grounding == "sam")
    return {"items": items, "spark": spark, "sam": sam}


def check_caps(c: dict[str, int]) -> None:
    if c["items"] > MAX_ITEMS or c["spark"] > MAX_SPARK_CALLS or c["sam"] > MAX_SAM_CALLS:
        raise SystemExit(f"plan exceeds the hard caps: {c}")


def run_imports() -> None:
    from import_corpus import append_items

    settings = get_settings()
    for domain, source, query, limit in PLAN:
        t0 = time.monotonic()
        try:
            items = list(SOURCES[source](domain, settings).search(query, limit))[:limit]
            added = append_items(MANIFEST_DIR / f"{domain}.jsonl", items)
            print(f"import {domain:8} {source:11} {query!r:30} found {len(items):4} new {added:4} "
                  f"({time.monotonic() - t0:.0f}s)", flush=True)  # fmt: skip
        except Exception as exc:
            print(f"import {domain:8} {source:11} {query!r:30} SKIPPED: {type(exc).__name__}: {exc}",
                  flush=True)  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", action="store_true", help="print the plan and exit")
    ap.add_argument("--skip-import", action="store_true")
    ap.add_argument("--yes", action="store_true", help="run: import, live indexing, seed")
    args = ap.parse_args(argv)
    counts = planned_calls()
    check_caps(counts)
    print(f"plan: up to {counts['items']} items (cap {MAX_ITEMS}), {counts['spark']} Muse Spark "
          f"calls (cap {MAX_SPARK_CALLS}), {counts['sam']} SAM calls (cap {MAX_SAM_CALLS})")  # fmt: skip
    if args.plan or not args.yes:
        if not args.plan:
            print("nothing run; add --yes to import, index with the live providers and seed")
        return 0
    if not args.skip_import:
        run_imports()
    import index_corpus
    import seed

    for domain in DOMAINS:
        print(f"-- index {domain}", flush=True)
        index_corpus.main(["--domain", domain, "--limit", str(INDEX_LIMIT[domain])])
    print("-- seed", flush=True)
    return seed.main(
        ["--no-index"]
    )  # never re-index the whole manifest, which would bypass the caps


if __name__ == "__main__":
    raise SystemExit(main())
