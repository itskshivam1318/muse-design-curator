import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.bundle.export import BundleError, export_board
from app.bundle.scope import FILE_DIRS, TABLE_ORDER, file_paths
from app.db.models import BoardItem, CorpusItem
from tests.integration.bundle.conftest import Built, add_vary_run


def read_rows(z: zipfile.ZipFile) -> dict[str, list[dict]]:  # type: ignore[type-arg]
    return {
        t: json.loads(z.read(f"rows/{t}.json"))
        for t in TABLE_ORDER
        if f"rows/{t}.json" in z.namelist()
    }


def test_exports_the_board_and_its_files(tmp_path: Path, db: Session, built_board: Built) -> None:
    m = export_board(db, built_board.id, tmp_path / "b.zip")
    z = zipfile.ZipFile(tmp_path / "b.zip")
    assert m["format"] == "muse-board/1" and m["board_id"] == built_board.id
    assert m["counts"]["board_items"] == 4 and m["counts"]["agent_steps"] == 2
    assert json.loads(z.read("manifest.json")) == m
    rows = read_rows(z)
    paths = file_paths(rows)
    assert any(p.startswith("uploads/") for p in paths)
    assert any(p.startswith("thumbs/") for p in paths)
    assert "masks/m-1.png" in paths
    assert all(p.startswith(FILE_DIRS) for p in paths)
    assert all(f"files/{rel}" in z.namelist() for rel in paths)
    assert m["files"] == len(paths)
    assert m["left_out"] == []


def test_orders_rows_so_references_come_first(
    tmp_path: Path, db: Session, built_board: Built
) -> None:
    export_board(db, built_board.id, tmp_path / "b.zip")
    rows = read_rows(zipfile.ZipFile(tmp_path / "b.zip"))
    ids = [r["id"] for r in rows["board_items"]]
    assert ids.index(built_board.image_a) < ids.index(built_board.chained)
    by_id = {r["id"]: r for r in rows["board_items"]}
    chained = by_id[built_board.chained]
    assert chained["created_at"] < by_id[built_board.image_a]["created_at"]  # time says otherwise
    options = [r["id"] for r in rows["explore_options"]]
    parent, child = built_board.options
    assert options.index(parent) < options.index(child)


def test_lists_what_it_leaves_out(tmp_path: Path, db: Session, built_board: Built) -> None:
    add_vary_run(db, built_board.id, built_board.image_a)
    m = export_board(db, built_board.id, tmp_path / "b.zip")
    assert m["left_out"] == ["variation_runs", "ui_events"]
    names = zipfile.ZipFile(tmp_path / "b.zip").namelist()
    assert "rows/variation_runs.json" not in names and "rows/ui_events.json" not in names


def test_refuses_a_board_with_licensed_items(
    tmp_path: Path, db: Session, built_board: Built
) -> None:
    db.add(
        CorpusItem(
            id="cx_1",
            domain="d",
            source="t",
            source_id="1",
            landing_url="u",
            image_url="u",
            license_code="cc0",
            attribution_text="a",
        )
    )
    db.flush()
    db.add(
        BoardItem(
            board_id=built_board.id,
            kind="image",
            origin="candidate",
            rights_status="licensed",
            corpus_item_id="cx_1",
        )
    )
    db.commit()
    with pytest.raises(BundleError) as e:
        export_board(db, built_board.id, tmp_path / "out" / "b.zip")
    assert e.value.code == "BOARD_HAS_LICENSED_ITEMS"
    assert not (tmp_path / "out").exists()


def test_unknown_board(tmp_path: Path, db: Session) -> None:
    with pytest.raises(BundleError) as e:
        export_board(db, "brd_nope", tmp_path / "out" / "b.zip")
    assert e.value.code == "BOARD_NOT_FOUND"
    assert not (tmp_path / "out").exists()
