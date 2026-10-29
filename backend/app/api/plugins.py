from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.config import get_settings
from app.db.models import BoardPlugin
from app.errors import AppError
from app.plugins import registry
from app.plugins.registry import Plugin

router = APIRouter(prefix="/api")


def require_enabled() -> None:
    if not get_settings().PLUGINS_ENABLED:
        raise AppError(404, "NOT_FOUND", "Plugins are turned off")


def plugin_to_dict(p: Plugin) -> dict[str, Any]:
    m = p.manifest
    return {
        "id": m.id, "name": m.name, "description": m.description, "mark": m.mark,
        "tint": m.tint, "ink": m.ink, "runner": m.runner, "runs_on": m.runs_on,
        "inputs": m.inputs.model_dump(), "params": m.params, "outputs": m.outputs,
        "secondary": m.secondary, "status": registry.status(p), "builtin": p.builtin,
    }  # fmt: skip


class PluginAdd(BaseModel):
    plugin_id: str


def _board_plugin_ids(session: SessionDep, board_id: str) -> dict[str, Any]:
    rows = session.scalars(select(BoardPlugin.plugin_id).where(BoardPlugin.board_id == board_id))
    return {"plugin_ids": sorted(rows)}


@router.get("/plugins")
def list_plugins() -> dict[str, Any]:
    require_enabled()
    return {"plugins": [plugin_to_dict(p) for p in registry.get_registry().values()]}


@router.get("/plugin-packs")
def list_packs() -> dict[str, Any]:
    require_enabled()
    return {"packs": registry.load_packs()}


@router.post("/plugins/reload")
def reload_plugins() -> dict[str, Any]:
    require_enabled()
    return registry.reload()


@router.get("/boards/{board_id}/plugins")
def board_plugins(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_enabled()
    require_board(session, board_id)
    return _board_plugin_ids(session, board_id)


@router.post("/boards/{board_id}/plugins")
def add_board_plugin(board_id: str, body: PluginAdd, session: SessionDep) -> dict[str, Any]:
    require_enabled()
    require_board(session, board_id)
    if body.plugin_id not in registry.get_registry():
        raise AppError(404, "PLUGIN_NOT_FOUND", "Unknown plugin")
    if session.get(BoardPlugin, (board_id, body.plugin_id)) is None:
        session.add(BoardPlugin(board_id=board_id, plugin_id=body.plugin_id))
        session.flush()
    return _board_plugin_ids(session, board_id)


@router.delete("/boards/{board_id}/plugins/{plugin_id}", status_code=204)
def remove_board_plugin(board_id: str, plugin_id: str, session: SessionDep) -> Response:
    require_enabled()
    require_board(session, board_id)
    session.execute(
        delete(BoardPlugin).where(
            BoardPlugin.board_id == board_id, BoardPlugin.plugin_id == plugin_id
        )
    )
    return Response(status_code=204)
