"""Command line for board bundles: `python -m app.bundle export|import`.

Uses the app's own database and DATA_DIR (DATABASE_URL and DATA_DIR env vars apply).
"""

import argparse
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.engine import make_url

from app.bundle.export import BundleError, export_board
from app.bundle.importer import import_board
from app.config import data_dir, get_settings
from app.db.session import make_engine_from_settings, make_session_factory, resolve_database_url
from app.storage.files import abs_path


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.bundle", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export", help="write a board to a bundle zip")
    e.add_argument("board_id")
    e.add_argument("out", type=Path)
    i = sub.add_parser("import", help="read a bundle zip into this app")
    i.add_argument("bundle", type=Path)
    i.add_argument(
        "--replace",
        action="store_true",
        help="replace the board if it is already here (removes Vary runs and decisions on it)",
    )
    return p


def _rows(manifest: dict[str, object]) -> int:
    counts = manifest["counts"]
    assert isinstance(counts, dict)
    return sum(counts.values())


def _new_files(bundle: Path) -> int:
    """How many of the bundle's files this server does not have yet (counted before importing)."""
    try:
        with zipfile.ZipFile(bundle) as z:
            names = [
                n[len("files/") :] for n in z.namelist() if n.startswith("files/") and n[-1] != "/"
            ]
    except (zipfile.BadZipFile, OSError):
        return 0  # import_board reports the unreadable bundle
    return sum(1 for rel in names if ".." not in rel.split("/") and not abs_path(rel).exists())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    url = make_url(resolve_database_url(settings)).render_as_string(hide_password=True)
    print(f"database {url}, files {data_dir(settings)}")  # which server's data this touches
    engine = make_engine_from_settings(settings)
    session = make_session_factory(engine)()
    try:
        if args.command == "export":
            manifest = export_board(session, args.board_id, args.out)
            print(
                f"exported {manifest['title']} ({manifest['board_id']}): "
                f"{_rows(manifest)} rows, {manifest['files']} files -> {args.out}"
            )
            if manifest["unfinished_items"]:
                print(
                    f"note: {manifest['unfinished_items']} items are not finished and will be "
                    "read again on the server (model calls)"
                )
        else:
            new_files = _new_files(args.bundle)
            manifest = import_board(session, args.bundle, replace=args.replace)
            session.commit()
            print(
                f"imported {manifest['title']} ({manifest['board_id']}): "
                f"{_rows(manifest)} rows, {new_files} new files"
            )
            removed = manifest.get("replaced_left_out")
            if removed:
                print(
                    "removed from this server: " + ", ".join(f"{t} {n}" for t, n in removed.items())
                )
    except BundleError as e:
        session.rollback()
        print(f"error {e.code}: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - any failure must roll back and exit 1
        session.rollback()
        print(f"error {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
