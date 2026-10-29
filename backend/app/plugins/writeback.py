"""Write a validated plugin result onto the board: new items beside the node, attributes on the
input items. Runs inside the run's final transaction; events go out after the commit."""

import base64
import io
import re
import uuid
from functools import partial
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events, jobs
from app.api.schemas import item_to_dict
from app.db.models import BoardItem, ItemAttribute, PluginNode, PluginRun
from app.db.repos import attributes as attrs_repo
from app.db.session import after_commit
from app.domain.attributes import RELIABLE_CONFIDENCE, Evidence, canonical_token
from app.domain.kinds import AttributeSpec, EnumSpec, NumberSpec, OrdinalSpec
from app.errors import AppError
from app.extraction.merge import USER_STATUSES
from app.extraction.service import _recompute, current_lens
from app.ingest.common import ItemMeta, create_item, default_size
from app.ingest.images import decode_image
from app.notes.service import create_note
from app.plugins.registry import get_registry
from app.plugins.runners import PluginError
from app.storage import files

COLUMN_GAP = 40  # node edge to the output column
STACK_GAP = 24  # between outputs in the column
DEFAULT_CONFIDENCE = {"python": 1.0, "llm": 0.7, "model": 1.0}
# Attribute changes are announced with the event the extraction pipeline sends when an item's
# attributes change (the attributes API itself sends none); the board refetches that item's
# attributes on it.
ATTRIBUTES_EVENT = "item.parsed"


def _stamped(img: Image.Image, plugin_id: str, run_id: str) -> bytes:
    """PNG bytes with provenance and a nonce, so identical results never collide on sha256."""
    info = PngInfo()
    info.add_text("Software", plugin_id)
    info.add_text("muse:plugin_run", run_id)
    info.add_text("muse:nonce", uuid.uuid4().hex)
    if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _column_top(session: Session, node: PluginNode, x: float, before: list[str]) -> float:
    """Below the outputs of this node's earlier runs still standing in the column."""
    if not before:
        return node.y
    rows = session.scalars(
        select(BoardItem).where(
            BoardItem.id.in_(before), BoardItem.removed_at.is_(None), BoardItem.x == x
        )
    )
    return max([node.y, *(i.y + i.h + STACK_GAP for i in rows)])


def _earlier_outputs(session: Session, run: PluginRun) -> list[str]:
    runs = session.scalars(
        select(PluginRun.output_json).where(
            PluginRun.node_id == run.node_id, PluginRun.id != run.id, PluginRun.status == "done"
        )
    )
    return [i for out in runs if isinstance(out, dict) for i in out.get("created_item_ids", [])]


def _image_item(
    session: Session, run: PluginRun, node: PluginNode, data_b64: str, x: float, y: float,
    model: str, parent: str | None,
) -> BoardItem:  # fmt: skip
    try:
        img = decode_image(base64.b64decode(data_b64))
    except AppError:
        raise PluginError("PLUGIN_BAD_OUTPUT", "an image in the result could not be read") from None
    data = _stamped(img, run.plugin_id, run.id)
    sha = files.sha256_hex(data)
    storage = files.save_original(data, sha, "png")
    thumb = files.save_thumb(img, sha)
    w, h = default_size(*img.size)
    meta = ItemMeta(origin="generated", filename=f"{run.plugin_id}.png", x=x, y=y)
    return create_item(
        session, node.board_id, meta,
        kind="image", sha256=sha, storage_path=storage, thumb_path=thumb, mime="image/png",
        width=img.size[0], height=img.size[1], w=w, h=h, rights_status="generated",
        parent_item_id=parent,
        generation_json={"plugin": run.plugin_id, "model": model, "run_id": run.id},
    )  # fmt: skip


def _kind(value: Any) -> str:
    if isinstance(value, bool):  # before int: a bool is an int
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "text"


def _scalar(value: Any) -> Any:
    """Values stay scalar: a list is stored as text."""
    return ", ".join(str(v) for v in value) if isinstance(value, list) else value


def _summary(row: ItemAttribute | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"value": row.value_json, "status": row.status, "confidence": row.confidence}


HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_UNFIT = object()


def _fit(value: Any, kind: str, spec: AttributeSpec | None) -> Any:
    """`value` as stored under an existing row of `kind`, or _UNFIT. enum/ordinal values must be
    one of the lens's options when the lens defines them."""
    if kind == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            return _UNFIT
        if isinstance(spec, NumberSpec) and not spec.min <= value <= spec.max:
            return _UNFIT
        return value
    if kind == "boolean":
        return value if isinstance(value, bool) else _UNFIT
    if not isinstance(value, str) or not value.strip():
        return _UNFIT
    if kind == "text":
        return value
    if kind == "color":
        return value.strip().lower() if HEX.match(value.strip()) else _UNFIT
    if kind in ("enum", "ordinal"):
        options: list[str] | None = None
        if isinstance(spec, EnumSpec) and spec.vocabulary and not spec.open_vocabulary:
            options = spec.vocabulary
        elif isinstance(spec, OrdinalSpec):
            options = spec.scale
        if options is None:
            return value
        token = canonical_token(value)
        return token if token in options else _UNFIT
    return _UNFIT  # shape and anything else a plugin cannot write


def _write_attributes(
    session: Session, run: PluginRun, attrs: list[dict[str, Any]], runner: str
) -> tuple[set[str], list[dict[str, str]]]:
    """Upsert each attribute unless the user owns it or the value does not fit the existing
    row's kind; returns (items touched, skipped)."""
    touched: set[str] = set()
    skipped: list[dict[str, str]] = []
    lens = current_lens(session, run.board_id)
    specs = {a.key: a for a in lens.attributes} if lens else {}
    for a in attrs:
        item_id, key = a["item_id"], a["key"]
        row = session.scalar(
            select(ItemAttribute).where(ItemAttribute.item_id == item_id, ItemAttribute.key == key)
        )
        if row is not None and (row.source == "user" or row.status in USER_STATUSES):
            skipped.append({"item_id": item_id, "key": key, "reason": "set by you"})
            continue
        value = _scalar(a["value"])
        if row is not None:
            value = _fit(value, row.kind, specs.get(key))
            if value is _UNFIT:
                reason = f"value does not fit {row.kind} {row.label!r}"
                skipped.append({"item_id": item_id, "key": key, "reason": reason})
                continue
        before = _summary(row)
        confidence = a.get("confidence", DEFAULT_CONFIDENCE[runner])
        fields: dict[str, Any] = {
            "value_json": value, "confidence": confidence,
            "status": "extracted" if confidence >= RELIABLE_CONFIDENCE else "uncertain",
            "source": "plugin", "source_detail": run.plugin_id,
            "evidence_json": Evidence().model_dump(mode="json"),
            "model_value_json": None, "model_confidence": None,
        }  # fmt: skip
        if row is None:  # a new, open attribute; an existing row keeps label, category, kind
            fields |= {"label": a.get("label") or key.replace("_", " ").capitalize(),
                       "category": "plugin", "kind": _kind(value), "part": None}  # fmt: skip
        row = attrs_repo.upsert(session, item_id, key, **fields)
        attrs_repo.append_event(
            session, item_id=item_id, key=key, actor="plugin", action="plugin",
            before_json=before, after_json=_summary(row),
        )  # fmt: skip
        touched.add(item_id)
    return touched, skipped


def apply_output(
    session: Session, run: PluginRun, node: PluginNode, out: dict[str, Any]
) -> dict[str, Any]:
    """Write `out` back and return the run's output_json:
    {text?, table?, created_item_ids, skipped_attributes}. Raises PluginError on bad images."""
    plugin = get_registry().get(run.plugin_id)
    runner = plugin.manifest.runner if plugin else "python"
    model = plugin.manifest.runs_on if plugin else run.plugin_id
    inputs = list(run.input_item_ids_json or [])
    image_inputs = set(
        session.scalars(
            select(BoardItem.id).where(
                BoardItem.id.in_(inputs), BoardItem.kind == "image",
                BoardItem.removed_at.is_(None), BoardItem.staged.is_(False),
            )
        )
    )  # fmt: skip
    parent = next((i for i in inputs if i in image_inputs), None)
    x = node.x + node.w + COLUMN_GAP
    y = _column_top(session, node, x, _earlier_outputs(session, run))
    created: list[str] = []
    for image in out.get("images", []):
        item = _image_item(session, run, node, image["data_b64"], x, y, model, parent)
        created.append(item.id)
        y += item.h + STACK_GAP
        added = item_to_dict(item)
        after_commit(session, partial(events.publish, item.board_id, "item.added", added))
        after_commit(session, partial(jobs.enqueue, "parse_item", item_id=item.id))
    for note in out.get("notes", []):
        item = create_note(session, node.board_id, note["text"], x, y)
        created.append(item.id)
        y += item.h + STACK_GAP
    touched, skipped = _write_attributes(session, run, out.get("attributes", []), runner)
    for item_id in sorted(touched):
        status = session.scalar(select(BoardItem.parse_status).where(BoardItem.id == item_id))
        data = {"item_id": item_id, "parse_status": status}
        after_commit(session, partial(events.publish, node.board_id, ATTRIBUTES_EVENT, data))
    if touched:
        after_commit(session, partial(_recompute, node.board_id))
    result: dict[str, Any] = {k: out[k] for k in ("text", "table") if k in out}
    result["created_item_ids"] = created
    result["skipped_attributes"] = skipped
    return result
