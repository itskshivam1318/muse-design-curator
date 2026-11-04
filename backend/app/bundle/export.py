"""Write one board, its rows and its files, to a zip bundle."""

import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bundle import scope
from app.db import models as m
from app.db.ids import now_iso
from app.db.session import alembic_config
from app.storage.files import abs_path


class BundleError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def schema_head() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None
    return head


def _left_out(session: Session, board_id: str) -> list[str]:
    runs = select(m.VariationRun.id).where(m.VariationRun.board_id == board_id)
    candidates = select(m.RunCandidate.id).where(m.RunCandidate.run_id.in_(runs))
    counted = {
        "variation_runs": m.VariationRun.board_id == board_id,
        "run_candidates": m.RunCandidate.run_id.in_(runs),
        "validation_results": m.ValidationResult.run_candidate_id.in_(candidates),
        "decisions": m.Decision.board_id == board_id,
        "plugin_nodes": m.PluginNode.board_id == board_id,
        "plugin_runs": m.PluginRun.board_id == board_id,
        "board_plugins": m.BoardPlugin.board_id == board_id,
        "ui_events": m.UiEvent.board_id == board_id,
    }
    models = {
        "variation_runs": m.VariationRun,
        "run_candidates": m.RunCandidate,
        "validation_results": m.ValidationResult,
        "decisions": m.Decision,
        "plugin_nodes": m.PluginNode,
        "plugin_runs": m.PluginRun,
        "board_plugins": m.BoardPlugin,
        "ui_events": m.UiEvent,
    }
    return [
        t
        for t in scope.LEFT_OUT
        if session.scalar(select(func.count()).select_from(models[t]).where(counted[t]))
    ]


def export_board(session: Session, board_id: str, out: Path) -> dict[str, Any]:
    """Write the bundle zip to `out` (all or nothing) and return its manifest."""
    board = session.get(m.Board, board_id)
    if board is None:
        raise BundleError("BOARD_NOT_FOUND", f"no board {board_id}")
    licensed = session.scalar(
        select(func.count())
        .select_from(m.BoardItem)
        .where(m.BoardItem.board_id == board_id, m.BoardItem.corpus_item_id.is_not(None))
    )
    if licensed:
        raise BundleError(
            "BOARD_HAS_LICENSED_ITEMS", f"{licensed} licensed corpus item(s) cannot be bundled"
        )
    rows = scope.board_rows(session, board_id)
    paths = scope.file_paths(rows)
    for rel in paths:
        if not rel.startswith(scope.FILE_DIRS) or not abs_path(rel).is_file():
            raise BundleError("FILE_MISSING", f"{rel} is not a stored file")
    manifest: dict[str, Any] = {
        "format": scope.FORMAT,
        "schema_head": schema_head(),
        "board_id": board_id,
        "title": board.title,
        "exported_at": now_iso(),
        "counts": {t: len(r) for t, r in rows.items() if r},
        "files": len(paths),
        "left_out": _left_out(session, board_id),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            for table, table_rows in rows.items():
                if table_rows:
                    z.writestr(f"rows/{table}.json", json.dumps(table_rows))
            for rel in paths:
                z.write(abs_path(rel), f"files/{rel}")
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return manifest
