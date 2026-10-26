from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from app.corpus.indexer import embeddings_path
from app.db.models import Board, BoardItem, CorpusAttribute, CorpusItem
from app.retrieval.config import RANKING_CONFIG as CFG
from app.retrieval.filters import source_from_board_item
from app.retrieval.pool import build_pool


def _setup(session: Session, data_dir: Path):
    vecs = np.eye(4, dtype=np.float32)
    vecs[3] = np.array([0.6, 0.8, 0, 0])
    embeddings_path().parent.mkdir(parents=True, exist_ok=True)
    np.save(embeddings_path(), vecs)
    rows = [("d", 0), ("d", 1), ("other", 2), ("d", 3)]
    ids = []
    for i, (dom, row) in enumerate(rows):
        c = CorpusItem(
            domain=dom, source="s", source_id=str(i), landing_url="u", image_url="i",
            license_code="cc0", attribution_text="a", indexing_status="indexed",
            embedding_row=row,
        )  # fmt: skip
        session.add(c)
        session.flush()
        ids.append(c.id)
    session.add(CorpusAttribute(
        item_id=ids[0], key="t", value_json="a", confidence=0.9, source="measured",
        measured_json={"lab": [1, 2, 3]},
    ))  # fmt: skip
    board = Board(title="b", domain="d")
    session.add(board)
    session.flush()
    return board, ids


def test_pool_restricted_to_board_domain_and_ranked(session: Session, data_dir: Path) -> None:
    board, ids = _setup(session, data_dir)
    pool = build_pool(session, board, [1, 0, 0, 0], [0, 1, 0, 0], CFG)
    assert [p.item.id for p in pool] == [ids[3], ids[0], ids[1]]
    assert ids[2] not in [p.item.id for p in pool]
    assert abs(pool[1].relevance - 0.6) < 1e-6
    assert abs(pool[0].relevance - (0.6 * 0.6 + 0.4 * 0.8)) < 1e-6
    assert pool[1].attrs["t"].measured == {"lab": [1, 2, 3]}


def test_centroid_missing_uses_source_only_and_size_capped(
    session: Session, data_dir: Path
) -> None:
    board, ids = _setup(session, data_dir)
    pool = build_pool(session, board, [1, 0, 0, 0], None, CFG.model_copy(update={"pool_size": 1}))
    assert [p.item.id for p in pool] == [ids[0]] and abs(pool[0].relevance - 1.0) < 1e-6


def test_board_items_never_in_pool(session: Session, data_dir: Path) -> None:
    board, _ids = _setup(session, data_dir)
    session.add(
        BoardItem(board_id=board.id, kind="image", origin="upload", embedding_json=[1, 0, 0, 0])
    )
    session.flush()
    pool = build_pool(session, board, [1, 0, 0, 0], None, CFG)
    assert all(isinstance(p.item, CorpusItem) for p in pool) and len(pool) == 3


def test_counts_never_fetched_invalid_and_excludes_them(session: Session, data_dir: Path) -> None:
    board, _ = _setup(session, data_dir)
    session.add(CorpusItem(
        domain="d", source="s", source_id="inv", landing_url="u", image_url="i",
        license_code="x", attribution_text="a", indexing_status="pending",
        provenance_status="invalid",
    ))  # fmt: skip
    session.flush()
    pool = build_pool(session, board, [1, 0, 0, 0], None, CFG)
    assert pool.meta.invalid_unindexed == 1 and len(pool) == 3


def test_no_embeddings_file_gives_empty_pool(session: Session, data_dir: Path) -> None:
    board = Board(title="b", domain="d")
    session.add(board)
    session.flush()
    assert list(build_pool(session, board, [1, 0], None, CFG)) == []


def test_source_from_board_item_computes_dhash(session: Session, data_dir: Path) -> None:
    import io

    from PIL import Image

    from app.corpus import hashing

    img = Image.new("RGB", (64, 64))
    img.putdata([(x * 4 % 256, y * 4 % 256, (x * y) % 256) for y in range(64) for x in range(64)])
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    (data_dir / "o").mkdir(parents=True)
    (data_dir / "o" / "x.png").write_bytes(data)
    bi = BoardItem(board_id="b", kind="image", origin="upload", sha256="abc",
                   storage_path="o/x.png", corpus_item_id="corpus_1")  # fmt: skip
    s = source_from_board_item(bi)
    assert s.dhash == hashing.dhash(data) and s.sha256 == "abc" and s.corpus_item_id == "corpus_1"
