import json
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.api.deps import get_session
from app.bundle.export import BundleError, export_board
from app.bundle.importer import MAX_MEMBER_BYTES, import_board
from app.bundle.scope import TABLE_ORDER, model_for
from app.db.models import Board, Lens
from app.db.session import make_engine, make_session_factory, run_migrations
from app.main import app
from tests.integration.bundle.conftest import Built
from tests.integration.bundle.test_export import read_rows


@pytest.fixture
def bundle(tmp_path: Path, db: Session, built_board: Built) -> Path:
    out = tmp_path / "b.zip"
    export_board(db, built_board.id, out)
    return out


@pytest.fixture
def second_dir(bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The second app's DATA_DIR; set only once the bundle has been exported from the first."""
    d = tmp_path / "second"
    monkeypatch.setenv("DATA_DIR", str(d))
    return d


@pytest.fixture
def second(second_dir: Path) -> Iterator[sessionmaker[Session]]:
    """A second, empty database built by the migrations."""
    engine = make_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    run_migrations(engine)
    yield make_session_factory(engine)
    engine.dispose()


def run_import(factory: sessionmaker[Session], path: Path, **kw: Any) -> dict[str, Any]:
    with factory() as s:
        m = import_board(s, path, **kw)
        s.commit()
    return m


def refused(factory: sessionmaker[Session], path: Path, **kw: Any) -> str:
    with factory() as s, pytest.raises(BundleError) as e:
        import_board(s, path, **kw)
    return e.value.code


def counts(factory: sessionmaker[Session]) -> dict[str, int]:
    with factory() as s:
        out = {
            t: s.scalar(select(func.count()).select_from(model_for(t))) or 0 for t in TABLE_ORDER
        }
    return {t: n for t, n in out.items() if n}


def rewrite(
    src: Path,
    dst: Path,
    *,
    edit: Callable[[str, bytes], bytes | None] = lambda name, data: data,
    add: dict[str, bytes] | None = None,
) -> Path:
    """Copy a bundle, passing each member through `edit` (None drops it), then adding `add`."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = edit(name, zin.read(name))
            if data is not None:
                zout.writestr(name, data)
        for name, data in (add or {}).items():
            zout.writestr(name, data)
    return dst


def nothing_written(factory: sessionmaker[Session], data: Path) -> bool:
    files = [p for p in data.rglob("*") if p.is_file()] if data.exists() else []
    return counts(factory) == {} and files == []


def test_imports_a_board_with_item_and_option_chains(
    client: TestClient,
    bundle: Path,
    second: sessionmaker[Session],
    built_board: Built,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with zipfile.ZipFile(bundle) as z:
        exported = read_rows(z)
        originals = {
            built_board.image_a: z.read(
                next(
                    f"files/{r['thumb_path']}"
                    for r in exported["board_items"]
                    if r["id"] == built_board.image_a
                )
            )
        }
    m = run_import(second, bundle)
    assert m["board_id"] == built_board.id
    with second() as s:
        for table, rows in exported.items():
            model = model_for(table)
            for row in rows:
                pk = tuple(row[c.name] for c in model.__table__.primary_key.columns)
                assert s.get(model, pk if len(pk) > 1 else pk[0]) is not None, (table, row)

    monkeypatch.setattr(deps, "_factory", lambda: second)

    def override() -> Iterator[Session]:
        with second() as s:
            yield s

    app.dependency_overrides[get_session] = override
    items = client.get(f"/api/boards/{built_board.id}/items")
    assert items.status_code == 200, items.text
    listed = {i["id"] for i in items.json()["items"]}
    assert {built_board.image_a, built_board.image_b, built_board.note} <= listed
    img = client.get(f"/api/items/{built_board.image_a}/image")
    assert img.status_code == 200
    assert img.content == originals[built_board.image_a]


def test_refuses_a_board_that_is_already_here(bundle: Path, second: sessionmaker[Session]) -> None:
    run_import(second, bundle)
    before = counts(second)
    assert refused(second, bundle) == "BOARD_EXISTS"
    assert counts(second) == before


def test_replace_leaves_one_copy(bundle: Path, second: sessionmaker[Session]) -> None:
    run_import(second, bundle)
    m = run_import(second, bundle, replace=True)
    assert counts(second) == m["counts"]


def test_refuses_another_schema(
    tmp_path: Path, bundle: Path, second: sessionmaker[Session], second_dir: Path
) -> None:
    def other_head(name: str, data: bytes) -> bytes:
        if name != "manifest.json":
            return data
        return json.dumps({**json.loads(data), "schema_head": "0000_other"}).encode()

    bad = rewrite(bundle, tmp_path / "bad.zip", edit=other_head)
    assert refused(second, bad) == "SCHEMA_MISMATCH"
    assert nothing_written(second, second_dir)


def _drop_one_thumb() -> Callable[[str, bytes], bytes | None]:
    dropped: list[str] = []

    def edit(name: str, data: bytes) -> bytes | None:
        if name.startswith("files/thumbs/") and not dropped:
            dropped.append(name)
            return None
        return data

    return edit


@pytest.mark.parametrize(
    "member,code",
    [
        ("files/../evil.txt", "UNSAFE_PATH"),
        ("/etc/x", "UNSAFE_PATH"),
        ("files/config/x.png", "UNSAFE_PATH"),
        (None, "MISSING_FILE"),  # None: drop one thumbs/ member
    ],
)
def test_refuses_unsafe_or_incomplete_bundles(
    member: str | None,
    code: str,
    tmp_path: Path,
    bundle: Path,
    second: sessionmaker[Session],
    second_dir: Path,
) -> None:
    if member is None:
        bad = rewrite(bundle, tmp_path / "bad.zip", edit=_drop_one_thumb())
    else:
        bad = rewrite(bundle, tmp_path / "bad.zip", add={member: b"x"})
    assert refused(second, bad) == code
    assert nothing_written(second, second_dir)


def test_refuses_a_member_over_50_mb(
    tmp_path: Path, bundle: Path, second: sessionmaker[Session], second_dir: Path
) -> None:
    assert MAX_MEMBER_BYTES == 50 * 1024 * 1024
    bad = rewrite(
        bundle, tmp_path / "bad.zip", add={"files/uploads/big.bin": bytes(MAX_MEMBER_BYTES + 1)}
    )
    assert refused(second, bad) == "FILE_TOO_LARGE"
    assert nothing_written(second, second_dir)


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("item_attributes", "item_id", "itm_someone_else"),  # onto another board's item
        ("board_items", "thumb_path", ["thumbs/x.webp"]),  # a path that is not a string
    ],
)
def test_refuses_rows_that_reach_outside_the_board(
    table: str,
    column: str,
    value: Any,
    tmp_path: Path,
    bundle: Path,
    second: sessionmaker[Session],
    second_dir: Path,
) -> None:
    def edit(name: str, data: bytes) -> bytes:
        if name != f"rows/{table}.json":
            return data
        rows = json.loads(data)
        rows[0][column] = value
        return json.dumps(rows).encode()

    bad = rewrite(bundle, tmp_path / "bad.zip", edit=edit)
    assert refused(second, bad) == "BAD_BUNDLE"
    assert nothing_written(second, second_dir)


def _with_lens(lens: dict[str, Any]) -> Callable[[str, bytes], bytes | None]:
    def edit(name: str, data: bytes) -> bytes:
        if name == "rows/boards.json":
            boards = json.loads(data)
            boards[0]["lens_id"] = lens["id"]
            return json.dumps(boards).encode()
        return data

    return edit


def _lens_row(**kw: Any) -> dict[str, Any]:
    return {
        "id": "lens_shared",
        "board_id": None,
        "domain": "d",
        "version": 1,
        "origin": "o",
        "status": "confirmed",
        "spec_json": {},
        "created_at": "2026-01-01T00:00:00+00:00",
        **kw,
    }


def test_skips_a_lens_that_is_already_here(
    tmp_path: Path, bundle: Path, second: sessionmaker[Session], built_board: Built
) -> None:
    lens = _lens_row()
    with second() as s:
        s.add(Lens(**lens))
        s.commit()
    with_lens = rewrite(
        bundle,
        tmp_path / "lens.zip",
        edit=_with_lens(lens),
        add={"rows/lenses.json": json.dumps([lens]).encode()},
    )
    run_import(second, with_lens)
    with second() as s:
        assert s.scalar(select(func.count()).select_from(Lens)) == 1
        board = s.get(Board, built_board.id)
        assert board is not None and board.lens_id == "lens_shared"


def test_refuses_a_lens_of_a_board_that_is_not_here(
    tmp_path: Path, bundle: Path, second: sessionmaker[Session], second_dir: Path
) -> None:
    lens = _lens_row(board_id="brd_elsewhere")
    foreign = rewrite(
        bundle,
        tmp_path / "lens.zip",
        edit=_with_lens(lens),
        add={"rows/lenses.json": json.dumps([lens]).encode()},
    )
    assert refused(second, foreign) == "FOREIGN_LENS"
    assert nothing_written(second, second_dir)


def test_replace_keeps_one_copy_of_the_boards_own_lens(
    tmp_path: Path, bundle: Path, second: sessionmaker[Session], built_board: Built
) -> None:
    lens = _lens_row(id="lens_own", board_id=built_board.id)
    own = rewrite(
        bundle,
        tmp_path / "lens.zip",
        edit=_with_lens(lens),
        add={"rows/lenses.json": json.dumps([lens]).encode()},
    )
    run_import(second, own)
    run_import(second, own, replace=True)
    with second() as s:
        assert s.scalars(select(Lens.id)).all() == ["lens_own"]
        board = s.get(Board, built_board.id)
        assert board is not None and board.lens_id == "lens_own"
