"""Read a board bundle into this app's database and DATA_DIR, refusing anything unsafe.

Every check runs before anything is written. Files are staged under DATA_DIR and moved into
place only once all of them have been read in full; rows go in last, in TABLE_ORDER, in the
caller's transaction (nothing here commits).
"""

import json
import os
import shutil
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, select, tuple_
from sqlalchemy.orm import Session

from app.bundle import scope
from app.bundle.export import BundleError, left_out_scope, schema_head
from app.db import models as m
from app.storage.files import abs_path, root

MAX_MEMBER_BYTES = 50 * 1024 * 1024
ROW_MEMBERS = {f"rows/{t}.json" for t in scope.TABLE_ORDER}
_CHUNK = 1024 * 1024


def _safe_relative(name: str) -> bool:
    """A plain relative POSIX path: no root, drive, backslash, empty, `.` or `..` part."""
    if not name or name.startswith("/") or "\\" in name or ":" in name:
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def _check_members(z: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in z.infolist():
        name = info.filename
        if info.is_dir():  # zip -r and Finder add these; nothing is read from them
            if not _safe_relative(name.rstrip("/")):
                raise BundleError("UNSAFE_PATH", f"{name!r} is not a safe path")
            continue
        if not _safe_relative(name):
            raise BundleError("UNSAFE_PATH", f"{name!r} is not a safe path")
        allowed = (
            name == "manifest.json"
            or name in ROW_MEMBERS
            or (name.startswith("files/") and name[len("files/") :].startswith(scope.FILE_DIRS))
        )
        if not allowed:
            raise BundleError("UNSAFE_PATH", f"{name!r} is outside the bundle layout")
        if name in members:
            raise BundleError("BAD_BUNDLE", f"{name!r} appears twice")
        if info.file_size > MAX_MEMBER_BYTES:
            raise BundleError("FILE_TOO_LARGE", f"{name} is over {MAX_MEMBER_BYTES} bytes")
        members[name] = info
    return members


def _copy_capped(z: zipfile.ZipFile, info: zipfile.ZipInfo, out: Any) -> None:
    """Copy one member to `out`, refusing it once more than MAX_MEMBER_BYTES come out."""
    read = 0
    try:
        with z.open(info) as f:
            while chunk := f.read(_CHUNK):
                read += len(chunk)
                if read > MAX_MEMBER_BYTES:
                    raise BundleError("FILE_TOO_LARGE", f"{info.filename} is over the limit")
                out.write(chunk)
    # a corrupt member, an unknown compression method, an encrypted member
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as e:
        raise BundleError("BAD_BUNDLE", f"{info.filename} cannot be read: {e}") from e


def _read_json(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> Any:
    chunks: list[bytes] = []

    class _Sink:
        def write(self, b: bytes) -> None:
            chunks.append(b)

    _copy_capped(z, info, _Sink())
    try:
        return json.loads(b"".join(chunks))
    except ValueError as e:
        raise BundleError("BAD_BUNDLE", f"{info.filename} is not JSON") from e


def _manifest(z: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = z.getinfo("manifest.json")
    except KeyError as e:
        raise BundleError("BAD_BUNDLE", "no manifest.json") from e
    if info.file_size > MAX_MEMBER_BYTES:
        raise BundleError("FILE_TOO_LARGE", "manifest.json is over the limit")
    manifest = _read_json(z, info)
    if not isinstance(manifest, dict) or manifest.get("format") != scope.FORMAT:
        raise BundleError("BAD_BUNDLE", f"not a {scope.FORMAT} bundle")
    if not isinstance(manifest.get("board_id"), str):
        raise BundleError("BAD_BUNDLE", "the manifest names no board")
    return manifest


def _table(name: str) -> Table:
    table: Table = scope.model_for(name).__table__
    return table


def _rows(
    z: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for t in scope.TABLE_ORDER:
        info = members.get(f"rows/{t}.json")
        data = _read_json(z, info) if info else []
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise BundleError("BAD_BUNDLE", f"rows/{t}.json is not a list of rows")
        table = _table(t)
        columns = set(table.columns.keys())
        pk = [c.name for c in table.primary_key.columns]
        # keys, references and paths are compared and joined below: plain values only
        plain = [
            c.name
            for c in table.columns
            if c.primary_key or c.foreign_keys or c.name in (*scope.FILE_COLUMNS, "lens_id")
        ]
        for r in data:
            if (
                not set(r) <= columns
                or any(r.get(c) is None for c in pk)
                or any(not isinstance(r.get(c), str | int | None) for c in plain)
            ):
                raise BundleError("BAD_BUNDLE", f"rows/{t}.json has a row this schema cannot hold")
        rows[t] = data
    return rows


def _check_contained(rows: dict[str, list[dict[str, Any]]], board_id: str) -> None:
    """Every reference a row makes stays inside the bundle (save a lens's board, checked later),
    so no imported row can attach itself to another board's rows."""
    if [b["id"] for b in rows["boards"]] != [board_id]:
        raise BundleError("BAD_BUNDLE", "the bundle must hold exactly the manifest's board")
    values: dict[tuple[str, str], set[Any]] = {}

    def present(table: str, column: str) -> set[Any]:
        if (table, column) not in values:
            values[table, column] = {r.get(column) for r in rows.get(table, [])}
        return values[table, column]

    for t in scope.TABLE_ORDER:
        for col in _table(t).columns:
            if t == "lenses" and col.name == "board_id":
                continue
            for fk in col.foreign_keys:
                target = fk.column.table.name
                allowed = present(target, fk.column.name) if target in scope.TABLE_ORDER else set()
                for r in rows[t]:
                    if r.get(col.name) is not None and r[col.name] not in allowed:
                        raise BundleError(
                            "BAD_BUNDLE", f"{t}.{col.name} = {r[col.name]!r} is not in the bundle"
                        )
    lens_id = rows["boards"][0].get("lens_id")
    if lens_id is not None and lens_id not in present("lenses", "id"):
        raise BundleError("BAD_BUNDLE", "the board's lens is not in the bundle")
    if any(r.get("board_id") != board_id for r in rows["agent_steps"]):
        raise BundleError("BAD_BUNDLE", "an agent step names another board")


def _check_files(paths: list[str], members: dict[str, zipfile.ZipInfo]) -> None:
    for rel in paths:
        if not _safe_relative(rel) or not rel.startswith(scope.FILE_DIRS):
            raise BundleError("UNSAFE_PATH", f"a row names {rel!r}")
        if f"files/{rel}" not in members:
            raise BundleError("MISSING_FILE", f"files/{rel} is not in the bundle")


def _lenses_to_insert(
    session: Session, lenses: list[dict[str, Any]], board_id: str
) -> list[dict[str, Any]]:
    """A bundled lens is this board's own or has no board; any other cannot be imported. A lens
    already here is kept as it is, unless it is this board's own (a replace deletes those first).
    """
    out = []
    for lens in lenses:
        owner = lens.get("board_id")
        if owner is not None and owner != board_id:
            raise BundleError("FOREIGN_LENS", f"lens {lens['id']} belongs to board {owner}")
        here = session.get(m.Lens, lens["id"])
        if here is not None and here.board_id != board_id:
            continue
        out.append(lens)
    return out


def _write_files(z: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], paths: list[str]) -> None:
    """Stage every missing file under DATA_DIR, then move each into place."""
    missing = [rel for rel in paths if not abs_path(rel).exists()]
    if not missing:
        return
    root().mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=root(), prefix=".import-"))
    try:
        staged = []
        for i, rel in enumerate(missing):
            tmp = staging / str(i)
            with open(tmp, "wb") as out:
                _copy_capped(z, members[f"files/{rel}"], out)
            staged.append((tmp, rel))
        for tmp, rel in staged:
            dest = abs_path(rel)
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _delete_left_out(session: Session, board_id: str) -> dict[str, int]:
    """Delete this board's rows in the tables a bundle leaves out (Vary runs, decisions, plugin
    rows, UI events made on this server); they refer to the rows a replace deletes. Returns the
    count deleted per table, for tables that had any."""
    deleted: dict[str, int] = {}
    for t, (model, where) in reversed(left_out_scope(board_id).items()):
        n = session.execute(delete(model).where(where)).rowcount  # type: ignore[attr-defined]
        if n:
            deleted[t] = n
    return deleted


def _delete_board(session: Session, board_id: str) -> None:
    """Delete this board's rows in the bundle's scope; lenses of other boards stay."""
    rows = scope.board_rows(session, board_id)
    rows["lenses"] = [r for r in rows["lenses"] if r["board_id"] == board_id]
    for t in reversed(scope.TABLE_ORDER):
        if not rows[t]:
            continue
        table = _table(t)
        pk = list(table.primary_key.columns)
        keys = [tuple(r[c.name] for c in pk) for r in rows[t]]
        session.execute(delete(table).where(tuple_(*pk).in_(keys)))


def import_board(session: Session, bundle: Path, *, replace: bool = False) -> dict[str, Any]:
    """Import the bundle at `bundle` into `session`'s database and DATA_DIR; return its manifest.
    Commits nothing: the caller commits (or rolls back) the rows."""
    try:
        z = zipfile.ZipFile(bundle)
    except (zipfile.BadZipFile, OSError) as e:
        raise BundleError("BAD_BUNDLE", f"{bundle} is not a zip: {e}") from e
    with z:
        manifest = _manifest(z)
        if manifest.get("schema_head") != schema_head():
            raise BundleError(
                "SCHEMA_MISMATCH",
                f"bundle schema {manifest.get('schema_head')}, this app {schema_head()}",
            )
        members = _check_members(z)
        rows = _rows(z, members)
        board_id: str = manifest["board_id"]
        _check_contained(rows, board_id)
        paths = scope.file_paths(rows)
        _check_files(paths, members)
        exists = session.scalar(select(m.Board.id).where(m.Board.id == board_id)) is not None
        if exists and not replace:
            raise BundleError("BOARD_EXISTS", f"board {board_id} is already here")
        rows["lenses"] = _lenses_to_insert(session, rows["lenses"], board_id)
        _write_files(z, members, paths)
    if exists:
        session.flush()
        manifest = {**manifest, "replaced_left_out": _delete_left_out(session, board_id)}
        _delete_board(session, board_id)
    for t in scope.TABLE_ORDER:
        if rows[t]:
            session.execute(_table(t).insert(), rows[t])
    if exists:
        session.expire_all()  # objects loaded for the delete describe rows that were replaced
    return manifest
