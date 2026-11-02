"""Which renderers can turn an option on an item into a take.

Built-ins come first and are on every board: Muse Image for images and UI screens, Spark rewrite
for text. Then the plugins added to the board whose manifest `renders` the item's kind (the
built-in image plugin is Muse Image itself, so it is not listed twice).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.types import ContentType
from app.db.models import BoardItem, BoardPlugin, ItemAttribute
from app.errors import AppError
from app.explore.service import _part_label
from app.plugins.registry import Plugin, get_registry

MUSE_IMAGE = "muse_image"
SPARK_REWRITE = "spark_rewrite"
PLUGIN_PREFIX = "plugin:"
IMAGE_PLUGIN = "image"  # the built-in plugin behind Muse Image


@dataclass
class RendererInfo:
    id: str
    title: str  # button line 1
    detail: str  # button line 2: the model and where it edits
    builtin: bool


def content_type(item: BoardItem) -> ContentType | None:
    """The item's analysed content type, else the one its kind implies (None: not renderable)."""
    if item.content_type in ("image", "ui", "text"):
        return item.content_type  # type: ignore[return-value]
    if item.kind == "note":
        return "text"
    if item.kind in ("image", "video"):
        return "image"
    return None


def is_physical(row: ItemAttribute | None) -> bool:
    return row is not None and row.dim_type == "physical" and bool(row.part)


def _image_detail(session: Session, ct: ContentType, row: ItemAttribute | None) -> str:
    if not is_physical(row):
        return "Muse Image · whole image, no mask"
    assert row is not None
    shape = "box" if ct == "ui" else "mask"
    return f"Muse Image · inside the {_part_label(session, row)} {shape}"


def _builtin(
    session: Session, ct: ContentType | None, row: ItemAttribute | None
) -> list[RendererInfo]:
    if ct in ("image", "ui"):
        return [RendererInfo(MUSE_IMAGE, "Generate image", _image_detail(session, ct, row), True)]
    if ct == "text":
        where = "this passage only" if is_physical(row) else "whole text"
        return [RendererInfo(SPARK_REWRITE, "Rewrite passage", f"Muse Spark · {where}", True)]
    return []


def board_plugins(session: Session, item: BoardItem) -> list[Plugin]:
    """The board's added plugins that render this item's kind, by plugin id."""
    added = session.scalars(
        select(BoardPlugin.plugin_id).where(BoardPlugin.board_id == item.board_id)
    )
    plugins = get_registry()
    return [
        plugins[pid]
        for pid in sorted(added)
        if pid != IMAGE_PLUGIN and pid in plugins and item.kind in plugins[pid].manifest.renders
    ]


def renderers_for(
    session: Session, item: BoardItem, row: ItemAttribute | None
) -> list[RendererInfo]:
    """Every renderer for `row` (the explored dimension; None is treated as abstract) on
    `item`, built-ins first. Empty: nothing accepts the item ("Connect a renderer")."""
    out = _builtin(session, content_type(item), row)
    for p in board_plugins(session, item):
        m = p.manifest
        out.append(RendererInfo(PLUGIN_PREFIX + m.id, m.name, m.runs_on, False))
    return out


def plugin_for(renderer_id: str) -> Plugin | None:
    """The plugin behind a plugin renderer id, if it is still in the registry."""
    if not renderer_id.startswith(PLUGIN_PREFIX):
        return None
    return get_registry().get(renderer_id[len(PLUGIN_PREFIX) :])


def can_run(session: Session, item: BoardItem, info: RendererInfo) -> bool:
    """Built-ins always run; a plugin only through the image.edit model path, on an image."""
    if info.builtin:
        return True
    p = plugin_for(info.id)
    return (
        p is not None and p.manifest.runner == "model" and p.manifest.model == "image.edit"
        and content_type(item) in ("image", "ui")
    )  # fmt: skip


def pick_renderer(
    session: Session, item: BoardItem, row: ItemAttribute | None, renderer_id: str | None
) -> RendererInfo:
    """The chosen renderer (the first when none is named). 400 NO_RENDERER when nothing
    renders the item, RENDERER_NOT_FOUND for an id not offered for it, RENDERER_UNSUPPORTED
    for a plugin that cannot run as a renderer."""
    infos = renderers_for(session, item, row)
    if not infos:
        raise AppError(400, "NO_RENDERER", "Connect a renderer to visualize this item")
    info = (
        infos[0] if renderer_id is None else next((r for r in infos if r.id == renderer_id), None)
    )
    if info is None:
        raise AppError(400, "RENDERER_NOT_FOUND", "That renderer is not available for this item")
    if not can_run(session, item, info):
        raise AppError(400, "RENDERER_UNSUPPORTED", f"{info.title} cannot render this option")
    return info
