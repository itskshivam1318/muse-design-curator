"""Create the four demo boards from licensed corpus items.

uv run python scripts/seed.py --fixtures     # index the committed test corpus, then seed
uv run python scripts/seed.py                # index corpus/manifests/<domain>.jsonl, then seed
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.config import REPO_ROOT
from app.corpus.indexer import index_corpus
from app.db.models import Board, CorpusItem
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.session import after_commit
from app.extraction import service as _extraction  # noqa: F401  (registers the parse job)
from app.ingest.common import default_size
from app.ingest.sniff import sniff_image
from app.storage import files

FIXTURE_MANIFEST = REPO_ROOT / "backend" / "tests" / "fixtures" / "corpus" / "manifest.jsonl"
MANIFEST_DIR = REPO_ROOT / "corpus" / "manifests"
MAX_ITEMS_PER_BOARD, MIN_ITEMS_PER_BOARD, BOARD_SHARE = 8, 3, 0.4
COLUMNS, CELL_W, CELL_H = 4, 360, 320

BOARDS: list[dict[str, str]] = [
    {
        "domain": "watch", "title": "Field watch, warmer",
        "context": "Dress-adjacent field watch for a 38 mm wrist. Keep it legible and plain, "
        "but warmer than steel and black.",
    },
    {
        "domain": "fashion", "title": "Unlined summer coat",
        "context": "A light, unlined coat for warm evenings. Quiet colour, soft shoulder, "
        "nothing that reads as workwear.",
    },
    {
        "domain": "interior", "title": "Reading corner",
        "context": "A small reading corner in a north-facing room. Low seating, one lamp, "
        "natural materials, little decoration.",
    },
    {
        "domain": "ui", "title": "Settings screen, calmer",
        "context": "A settings screen for a note-taking app. Fewer boxes and borders, "
        "clear grouping, one accent colour.",
    },
]  # fmt: skip


def seed_board(session: Session, spec: dict[str, str], limit: int = MAX_ITEMS_PER_BOARD) -> Board:
    """One board of licensed, indexed corpus items for the spec's domain. Safe to re-run.

    The board takes at most 40% of the domain's valid indexed items (3 to `limit`), every other
    one by id, so the rest stay in the pool for Vary to draw candidates from.
    """
    existing = session.scalars(
        select(Board).where(Board.title == spec["title"], Board.domain == spec["domain"])
    ).first()
    if existing is not None:
        return existing
    board = boards_repo.create(
        session, title=spec["title"], context=spec["context"], domain=spec["domain"]
    )
    q = (
        select(CorpusItem)
        .where(
            CorpusItem.domain == spec["domain"], CorpusItem.indexing_status == "indexed",
            CorpusItem.provenance_status == "valid", CorpusItem.local_path.is_not(None),
        )
        .order_by(CorpusItem.id)
    )  # fmt: skip
    pool: list[CorpusItem] = []
    shas: set[str] = set()
    for cx in session.scalars(q):  # one board holds a given image once
        if cx.sha256 and cx.sha256 not in shas:
            shas.add(cx.sha256)
            pool.append(cx)
    take = min(limit, max(MIN_ITEMS_PER_BOARD, int(len(pool) * BOARD_SHARE)), len(pool))
    chosen = pool[::2][:take]
    chosen += [c for c in pool if c not in chosen][: take - len(chosen)]
    for i, cx in enumerate(chosen):
        path = files.abs_path(cx.local_path or "")
        data = path.read_bytes()
        mime, _ext = sniff_image(data) or ("image/jpeg", "jpg")
        with Image.open(path) as im:
            thumb = files.save_thumb(im, cx.sha256 or files.sha256_hex(data))
        w, h = default_size(cx.width or 1, cx.height or 1)
        jitter = (i * 37) % 28 - 14
        item = items_repo.create(
            session, board_id=board.id, kind="image", origin="seed", rights_status="licensed",
            corpus_item_id=cx.id, sha256=cx.sha256, storage_path=cx.local_path, thumb_path=thumb,
            mime=mime, width=cx.width, height=cx.height, w=w, h=h, z=i,
            x=float((i % COLUMNS) * CELL_W + jitter), y=float((i // COLUMNS) * CELL_H - jitter),
            source_url=cx.landing_url, page_url=cx.landing_url, creator_handle=cx.creator_name,
            original_filename=Path(cx.local_path or "").name,
        )  # fmt: skip
        after_commit(session, partial(jobs.enqueue, "parse_item", item_id=item.id))
    return board


def seed(session: Session) -> list[Board]:
    """Create the four demo boards (commit is the caller's)."""
    return [seed_board(session, spec) for spec in BOARDS]


def index_all(session: Session, fixtures: bool) -> None:
    for spec in BOARDS:
        domain = spec["domain"]
        manifest = FIXTURE_MANIFEST if fixtures else MANIFEST_DIR / f"{domain}.jsonl"
        if not manifest.is_file():
            print(f"{domain}: no manifest at {manifest}, skipped")
            continue
        report = index_corpus(session, domain, manifest)
        print(f"{domain}: {report.indexed} indexed, {report.skipped} unchanged, "
              f"{report.failed} failed, {report.invalid} invalid")  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixtures", action="store_true", help="use the committed test corpus")
    args = ap.parse_args(argv)
    from app.api import deps

    session = deps.new_session()
    try:
        index_all(session, args.fixtures)
        boards = seed(session)
        session.commit()
        for b in boards:
            n = len(items_repo.list_active(session, b.id))
            print(f"board {b.title!r} ({b.domain}): {n} items")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
