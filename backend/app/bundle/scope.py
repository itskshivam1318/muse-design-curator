"""What a board bundle carries: which tables, in what order, and which files."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m

FORMAT = "muse-board/1"
# every prefix app.storage.files and the part-mask writer put a stored file under
FILE_DIRS = ("uploads/", "thumbs/", "masks/", "frames/")
LEFT_OUT = (
    "variation_runs",
    "run_candidates",
    "validation_results",
    "decisions",
    "plugin_nodes",
    "plugin_runs",
    "board_plugins",
    "ui_events",
)
# insert order: a table comes after every table its rows refer to
TABLE_ORDER = (
    "boards",
    "lenses",
    "board_items",
    "item_frames",
    "item_attributes",
    "item_parts",
    "attribute_events",
    "explorations",
    "explore_options",
    "board_profiles",
    "agent_runs",
    "agent_steps",
)
# columns that point at another row of the same table
SELF_REFS = {
    "board_items": ("parent_item_id", "put_source_item_id"),
    "explore_options": ("parent_option_id",),
}
# columns that hold another row's id without a foreign key (the FK would make a cycle)
NON_FK_REFS = {
    ("board_items", "explore_option_id"): ("explore_options", "id"),
    ("explore_options", "kept_item_id"): ("board_items", "id"),
}
FILE_COLUMNS = ("storage_path", "thumb_path", "mask_path")

_MODELS: dict[str, Any] = {
    "boards": m.Board,
    "lenses": m.Lens,
    "board_items": m.BoardItem,
    "item_frames": m.ItemFrame,
    "item_attributes": m.ItemAttribute,
    "item_parts": m.ItemPart,
    "attribute_events": m.AttributeEvent,
    "explorations": m.Exploration,
    "explore_options": m.ExploreOption,
    "board_profiles": m.BoardProfile,
    "agent_runs": m.AgentRun,
    "agent_steps": m.AgentStep,
}


def model_for(table: str) -> Any:
    return _MODELS[table]


def _as_dict(row: Any) -> dict[str, Any]:
    return {c.name: getattr(row, c.key) for c in row.__table__.columns}


def _references_first(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Stable topological order: each row follows the rows it refers to (within `rows`)."""
    by_id = {r["id"]: r for r in rows}
    out: list[dict[str, Any]] = []
    done: set[str] = set()

    def visit(row: dict[str, Any], path: frozenset[str]) -> None:
        if row["id"] in done or row["id"] in path:  # a cycle cannot be ordered; keep what we have
            return
        for col in columns:
            ref = by_id.get(row[col]) if row[col] else None
            if ref is not None:
                visit(ref, path | {row["id"]})
        done.add(row["id"])
        out.append(row)

    for r in rows:
        visit(r, frozenset())
    return out


def _select(session: Session, table: str, *where: Any) -> list[dict[str, Any]]:
    model = _MODELS[table]
    stmt = select(model).where(*where)
    if hasattr(model, "created_at"):
        stmt = stmt.order_by(model.created_at, model.id)
    rows = [_as_dict(r) for r in session.scalars(stmt)]
    if table in SELF_REFS:
        rows = _references_first(rows, SELF_REFS[table])
    return rows


def board_rows(session: Session, board_id: str) -> dict[str, list[dict[str, Any]]]:
    """Table name -> this board's rows as column dicts, tables in TABLE_ORDER."""
    boards = _select(session, "boards", m.Board.id == board_id)
    lens_ids = [b["lens_id"] for b in boards if b["lens_id"]]
    lens_match = m.Lens.board_id == board_id
    if lens_ids:
        lens_match = lens_match | m.Lens.id.in_(lens_ids)
    items = _select(session, "board_items", m.BoardItem.board_id == board_id)
    item_ids = [r["id"] for r in items]
    explorations = _select(session, "explorations", m.Exploration.board_id == board_id)
    runs = _select(session, "agent_runs", m.AgentRun.board_id == board_id)
    out: dict[str, list[dict[str, Any]]] = {
        "boards": boards,
        "lenses": _select(session, "lenses", lens_match),
        "board_items": items,
        "item_frames": _select(session, "item_frames", m.ItemFrame.item_id.in_(item_ids)),
        "item_attributes": _select(
            session, "item_attributes", m.ItemAttribute.item_id.in_(item_ids)
        ),
        "item_parts": _select(session, "item_parts", m.ItemPart.item_id.in_(item_ids)),
        "attribute_events": _select(
            session, "attribute_events", m.AttributeEvent.item_id.in_(item_ids)
        ),
        "explorations": explorations,
        "explore_options": _select(
            session,
            "explore_options",
            m.ExploreOption.exploration_id.in_([r["id"] for r in explorations]),
        ),
        "board_profiles": _select(session, "board_profiles", m.BoardProfile.board_id == board_id),
        "agent_runs": runs,
        "agent_steps": _select(
            session, "agent_steps", m.AgentStep.run_id.in_([r["id"] for r in runs])
        ),
    }
    return {t: out[t] for t in TABLE_ORDER}


def file_paths(rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Every stored file the rows name, deduplicated and sorted."""
    found = {
        row[col]
        for table_rows in rows.values()
        for row in table_rows
        for col in FILE_COLUMNS
        if row.get(col)
    }
    return sorted(found)
