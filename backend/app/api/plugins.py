from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.api.boards import require_board
from app.api.deps import SessionDep
from app.config import get_settings
from app.db.models import BoardPlugin, PluginRun
from app.errors import AppError
from app.plugins import registry, service
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


# ---- nodes and runs ----


class NodeCreate(BaseModel):
    plugin_id: str
    x: float
    y: float
    input_item_ids: list[str] = []


class NodePatch(BaseModel):
    x: float | None = None
    y: float | None = None
    input_item_ids: list[str] | None = None
    params: dict[str, Any] | None = None


@router.get("/boards/{board_id}/nodes")
def list_nodes(board_id: str, session: SessionDep) -> dict[str, Any]:
    require_enabled()
    require_board(session, board_id)
    nodes = service.list_nodes(session, board_id)
    run_ids = [n.last_run_id for n in nodes if n.last_run_id]
    runs = list(session.scalars(select(PluginRun).where(PluginRun.id.in_(run_ids))))
    return {
        "nodes": [service.node_to_dict(n) for n in nodes],
        "runs": {r.node_id: service.run_to_dict(r) for r in runs},
    }


@router.post("/boards/{board_id}/nodes", status_code=201)
def create_node(board_id: str, body: NodeCreate, session: SessionDep) -> dict[str, Any]:
    require_enabled()
    require_board(session, board_id)
    node = service.create_node(
        session, board_id, body.plugin_id, body.x, body.y, body.input_item_ids
    )
    return service.node_to_dict(node)


@router.patch("/nodes/{node_id}")
def patch_node(node_id: str, body: NodePatch, session: SessionDep) -> dict[str, Any]:
    require_enabled()
    node = service.update_node(
        session, node_id, x=body.x, y=body.y, input_item_ids=body.input_item_ids,
        params=body.params,
    )  # fmt: skip
    return service.node_to_dict(node)


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: str, session: SessionDep) -> Response:
    require_enabled()
    service.remove_node(session, node_id)
    return Response(status_code=204)


@router.post("/nodes/{node_id}/run", status_code=202)
def run_node(node_id: str, session: SessionDep) -> JSONResponse:
    require_enabled()
    run = service.request_run(session, node_id)
    session.commit()  # the job runs after this commit; answer with the run as it is now
    session.refresh(run)
    return JSONResponse(service.run_to_dict(run), status_code=202)


@router.get("/plugin-runs/{run_id}")
def get_run(run_id: str, session: SessionDep) -> dict[str, Any]:
    require_enabled()
    run = session.get(PluginRun, run_id)
    if run is None:
        raise AppError(404, "RUN_NOT_FOUND", "Run not found")
    return service.run_to_dict(run)
