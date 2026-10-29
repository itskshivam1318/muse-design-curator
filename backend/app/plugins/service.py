"""Plugin nodes on a board and their runs.

A node is an added plugin placed on the canvas with its input items and params. Run creates a
`queued` run (its `claimed_at` is the claim), points the node at it and queues the `plugin_run`
job; the job runs the plugin and writes the result back. No job survives a restart, so startup
marks queued and running runs `PLUGIN_INTERRUPTED`.
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import events, jobs
from app.config import get_settings
from app.db.ids import now_iso
from app.db.models import Board, BoardItem, BoardPlugin, PluginNode, PluginRun
from app.db.repos import attributes as attrs_repo
from app.db.session import after_commit
from app.errors import AppError
from app.explore.visualize import _iso
from app.extraction.service import _image_for
from app.notes.service import board_notes_context
from app.plugins import writeback
from app.plugins.registry import Plugin, get_registry, status
from app.plugins.runners import (
    BoardCtx,
    PluginError,
    RunInput,
    check_input_kinds,
    check_params,
    run_plugin,
)

log = logging.getLogger(__name__)

JOB = "plugin_run"
NODE_W = 300
NODE_H = 360
ACTIVE = ("queued", "running")


# ---- dicts ---------------------------------------------------------------------------------


def node_to_dict(n: PluginNode) -> dict[str, Any]:
    return {
        "id": n.id, "board_id": n.board_id, "plugin_id": n.plugin_id,
        "x": n.x, "y": n.y, "w": n.w, "h": n.h,
        "input_item_ids": list(n.input_item_ids_json or []), "params": n.params_json or {},
        "last_run_id": n.last_run_id,
    }  # fmt: skip


def run_to_dict(r: PluginRun) -> dict[str, Any]:
    return {
        "id": r.id, "node_id": r.node_id, "plugin_id": r.plugin_id, "status": r.status,
        "progress": r.progress_json, "output": r.output_json, "error_code": r.error_code,
        "error_message": r.error_message, "created_at": r.created_at,
        "finished_at": r.finished_at,
    }  # fmt: skip


# ---- nodes ---------------------------------------------------------------------------------


def _plugin(plugin_id: str) -> Plugin:
    p = get_registry().get(plugin_id)
    if p is None:
        raise AppError(404, "PLUGIN_NOT_FOUND", "Unknown plugin")
    return p


def _params(p: Plugin, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return check_params(p.manifest, params)
    except PluginError as e:
        raise AppError(400, e.code, e.message) from None


def _check_items(session: Session, board_id: str, ids: list[str]) -> list[str]:
    """Live, unstaged items of this board, in order, without repeats."""
    ids = list(dict.fromkeys(ids))
    found = set(
        session.scalars(
            select(BoardItem.id).where(
                BoardItem.id.in_(ids), BoardItem.board_id == board_id,
                BoardItem.removed_at.is_(None), BoardItem.staged.is_(False),
            )
        )
    )  # fmt: skip
    missing = [i for i in ids if i not in found]
    if missing:
        raise AppError(400, "ITEM_NOT_FOUND", f"Item {missing[0]} is not on this board")
    return ids


def require_node(session: Session, node_id: str) -> PluginNode:
    n = session.get(PluginNode, node_id)
    if n is None or n.removed_at is not None:
        raise AppError(404, "NODE_NOT_FOUND", "Node not found")
    return n


def list_nodes(session: Session, board_id: str) -> list[PluginNode]:
    q = select(PluginNode).where(PluginNode.board_id == board_id, PluginNode.removed_at.is_(None))
    return list(session.scalars(q.order_by(PluginNode.created_at, PluginNode.id)))


def create_node(
    session: Session, board_id: str, plugin_id: str, x: float, y: float, input_item_ids: list[str]
) -> PluginNode:
    if session.get(BoardPlugin, (board_id, plugin_id)) is None:
        raise AppError(400, "PLUGIN_NOT_ADDED", "Add this plugin to the board first")
    p = _plugin(plugin_id)
    node = PluginNode(
        board_id=board_id, plugin_id=plugin_id, x=x, y=y, w=NODE_W, h=NODE_H,
        input_item_ids_json=_check_items(session, board_id, input_item_ids),
        params_json=_params(p, {}),
    )  # fmt: skip
    session.add(node)
    session.flush()
    return node


def update_node(
    session: Session, node_id: str, *, x: float | None = None, y: float | None = None,
    input_item_ids: list[str] | None = None, params: dict[str, Any] | None = None,
) -> PluginNode:  # fmt: skip
    node = require_node(session, node_id)
    if x is not None:
        node.x = x
    if y is not None:
        node.y = y
    if input_item_ids is not None:
        node.input_item_ids_json = _check_items(session, node.board_id, input_item_ids)
    if params is not None:
        node.params_json = _params(_plugin(node.plugin_id), params)
    session.flush()
    return node


def remove_node(session: Session, node_id: str) -> None:
    require_node(session, node_id).removed_at = now_iso()
    session.flush()


# ---- runs ----------------------------------------------------------------------------------


def claim_ttl_s() -> int:
    return max(get_settings().PLUGIN_TIMEOUT_S * 2, 120)


def _publish(session: Session, board_id: str, kind: str, data: dict[str, Any]) -> None:
    after_commit(session, partial(events.publish, board_id, kind, data))


def _fail(run: PluginRun, code: str, message: str) -> None:
    run.status, run.error_code, run.error_message = "failed", code, message
    run.finished_at = now_iso()


def request_run(session: Session, node_id: str) -> PluginRun:
    """Queue a run of the node. 409 while its latest run is queued or running, unless that
    claim is older than the TTL (its job died); the stale run is then marked interrupted."""
    node = require_node(session, node_id)
    p = _plugin(node.plugin_id)
    prev = session.get(PluginRun, node.last_run_id) if node.last_run_id else None
    if prev is not None and prev.status in ACTIVE:
        stale = _iso(datetime.now(UTC) - timedelta(seconds=claim_ttl_s()))
        if prev.claimed_at is not None and prev.claimed_at >= stale:
            raise AppError(409, "NODE_RUNNING", "This node is already running")
        _fail(prev, "PLUGIN_INTERRUPTED", "The run stopped before it finished")
    if session.get(BoardPlugin, (node.board_id, node.plugin_id)) is None:
        raise AppError(400, "PLUGIN_NOT_ADDED", "Add this plugin to the board to run it")
    if status(p) != "available":
        raise AppError(400, "PLUGIN_NOT_CONNECTED", f"{p.manifest.name} is not connected")
    _check_live_inputs(session, node, p)
    run = PluginRun(
        board_id=node.board_id, node_id=node.id, plugin_id=node.plugin_id,
        input_item_ids_json=list(node.input_item_ids_json or []),
        params_json=dict(node.params_json or {}), status="queued",
        claimed_at=_iso(datetime.now(UTC)),
    )  # fmt: skip
    session.add(run)
    session.flush()
    # compare-and-set on the node: of two racing requests only one points it at its run
    moved = session.execute(
        update(PluginNode)
        .where(PluginNode.id == node.id, _same(PluginNode.last_run_id, node.last_run_id))
        .values(last_run_id=run.id)
    )
    if not moved.rowcount:  # type: ignore[attr-defined]
        raise AppError(409, "NODE_RUNNING", "This node is already running")
    session.refresh(node)
    _publish(session, node.board_id, "plugin_run.queued", {"node_id": node.id, "run_id": run.id})
    after_commit(session, partial(jobs.enqueue, JOB, run_id=run.id))
    return run


def _check_live_inputs(session: Session, node: PluginNode, p: Plugin) -> None:
    """400 before queueing when the inputs still on the board cannot satisfy the plugin."""
    ids = list(node.input_item_ids_json or [])
    kinds = {
        i.id: i.kind
        for i in session.scalars(select(BoardItem).where(BoardItem.id.in_(ids)))
        if i.removed_at is None and not i.staged
    }
    try:
        check_input_kinds(p.manifest, [kinds[i] for i in ids if i in kinds])
    except PluginError as e:
        raise AppError(400, e.code, e.message) from None


def _same(col: Any, value: str | None) -> Any:
    return col.is_(None) if value is None else col == value


def _label(item: BoardItem) -> str:
    return item.page_title or item.original_filename or item.kind


def _inputs(session: Session, run: PluginRun, p: Plugin) -> list[RunInput]:
    """The run's input items still on the board (removed and staged ones are skipped)."""
    ids = list(run.input_item_ids_json or [])
    rows = {
        i.id: i
        for i in session.scalars(select(BoardItem).where(BoardItem.id.in_(ids)))
        if i.removed_at is None and not i.staged
    }
    live = [rows[i] for i in ids if i in rows]
    if len(live) < len(ids) and len(live) < p.manifest.inputs.min:
        raise PluginError("PLUGIN_BAD_INPUT", "Some inputs were removed")
    out = []
    for item in live:
        image = None
        if item.kind in ("image", "video"):
            try:
                image = _image_for(session, item)[0]
            except AppError:
                image = None
        attrs = {r.key: r.value_json for r in attrs_repo.for_item(session, item.id) if r.enabled}
        out.append(RunInput(id=item.id, kind=item.kind, label=_label(item), attributes=attrs,
                            note_text=item.note_text, image=image))  # fmt: skip
    return out


def _board(session: Session, board_id: str) -> BoardCtx:
    b = session.get(Board, board_id)
    return BoardCtx(
        title=b.title if b else "", context=b.context if b else None,
        notes=board_notes_context(session, board_id),
    )  # fmt: skip


def _progress(session: Session, run_id: str, board_id: str, node_id: str, message: str) -> None:
    # progress is also the heartbeat: a healthy long run never looks stale to request_run
    session.execute(
        update(PluginRun)
        .where(PluginRun.id == run_id)
        .values(progress_json={"message": message}, claimed_at=_iso(datetime.now(UTC)))
    )
    data = {"node_id": node_id, "run_id": run_id, "progress": {"message": message}}
    _publish(session, board_id, "plugin_run.progress", data)
    session.commit()


def _finish_failed(session: Session, run_id: str, code: str, message: str) -> None:
    session.rollback()
    run = session.get(PluginRun, run_id)
    if run is None or run.status not in ACTIVE:
        return
    _fail(run, code, message)
    data = {"node_id": run.node_id, "run_id": run.id, "error_code": code, "error_message": message}
    _publish(session, run.board_id, "plugin_run.failed", data)
    session.commit()


def execute_run(session: Session, run_id: str) -> None:
    claimed = session.execute(
        update(PluginRun)
        .where(PluginRun.id == run_id, PluginRun.status == "queued")
        .values(status="running", claimed_at=_iso(datetime.now(UTC)))
    )
    if not claimed.rowcount:  # type: ignore[attr-defined]
        return  # superseded, or already taken
    session.commit()
    run = session.get(PluginRun, run_id)
    assert run is not None
    board_id, node_id = run.board_id, run.node_id
    try:
        p = _plugin(run.plugin_id)
        inputs = _inputs(session, run, p)
        board = _board(session, board_id)
        params = dict(run.params_json or {})
        out = run_plugin(
            p, inputs, params, board, partial(_progress, session, run_id, board_id, node_id)
        )
        session.expire_all()
        run = session.get(PluginRun, run_id)
        node = session.get(PluginNode, node_id)
        if run is None or node is None or run.status != "running":
            session.rollback()  # interrupted while it ran: a newer run owns the node
            return
        result = writeback.apply_output(session, run, node, out)
    except PluginError as e:
        _finish_failed(session, run_id, e.code, e.message)
        return
    except AppError as e:  # e.g. the plugin left the registry on a reload
        _finish_failed(session, run_id, e.code, e.message)
        return
    run.status, run.output_json, run.finished_at = "done", result, now_iso()
    run.progress_json = None
    data = {"node_id": node_id, "run_id": run_id, "output": result}
    _publish(session, board_id, "plugin_run.done", data)
    session.commit()


def plugin_run_job(run_id: str) -> None:
    from app.api import deps

    with deps._factory()() as session:
        try:
            execute_run(session, run_id)
        except Exception:
            log.exception("plugin run %s failed", run_id)
            _finish_failed(session, run_id, "PLUGIN_CRASHED", "Something went wrong")


def recover_stuck_runs(session: Session) -> int:
    """Startup: queued and running runs lost their job; mark them interrupted."""
    stuck = list(session.scalars(select(PluginRun).where(PluginRun.status.in_(ACTIVE))))
    for run in stuck:
        _fail(run, "PLUGIN_INTERRUPTED", "The run stopped before it finished")
    session.flush()
    return len(stuck)


jobs.register(JOB, plugin_run_job)
