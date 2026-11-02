"""What the analyser is told about the board and the item, and what Muse learns from the board."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import partial
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events
from app.analysis.analysers import Hints
from app.board.profile import compute_profile
from app.db.models import BoardItem, Exploration, ExploreOption, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.session import after_commit

USER_SOURCES = ("you", "user")


MAX_LEARNED = 12
MAX_DEFINITIONS = 12
OFFER_MIN_ITEMS = 2


def board_context(session: Session, board_id: str) -> str:
    board = boards_repo.get(session, board_id)
    if board is None:
        return ""
    lines = [f"Board: {board.title}", f"Your words: {board.context or ''}"]
    learned = [str(x) for x in (board.learned_json or [])][:MAX_LEARNED]
    if learned:
        lines.append("What Muse has learned:")
        lines.extend(f"- {line}" for line in learned)
    return "\n".join(lines)


def _current_rows(session: Session, board_id: str) -> list[tuple[BoardItem, ItemAttribute]]:
    q = (
        select(BoardItem, ItemAttribute)
        .join(ItemAttribute, ItemAttribute.item_id == BoardItem.id)
        .where(
            BoardItem.board_id == board_id,
            BoardItem.removed_at.is_(None),
            BoardItem.staged.is_(False),
            ItemAttribute.removed.is_(False),
            ItemAttribute.status != "stale",
        )
        .order_by(BoardItem.id, ItemAttribute.key)
    )
    return [(i, a) for i, a in session.execute(q).all()]


def _abstract_definitions(session: Session, board_id: str) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for _item, a in _current_rows(session, board_id):
        if a.dim_type == "abstract" and a.prompt:
            counts[(a.label, a.prompt)] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_DEFINITIONS]
    return [{"label": label, "prompt": prompt} for (label, prompt), _n in ranked]


def hints_for(session: Session, board_id: str, item_id: str) -> Hints:
    """Board dimensions and abstract definitions in use, plus the item's own parts and
    dimensions, what the user removed, and the source item's dimensions."""
    hints = Hints.empty()
    board = boards_repo.get(session, board_id)
    if board is not None:
        hints.board_dimensions = [dict(d) for d in (board.dimensions_json or [])]
    hints.abstract_definitions = _abstract_definitions(session, board_id)
    parts = session.scalars(select(ItemPart).where(ItemPart.item_id == item_id))
    attrs = session.scalars(select(ItemAttribute).where(ItemAttribute.item_id == item_id))
    for p in parts:
        if p.removed:
            hints.removed.append(p.key)
        elif p.source == "you":
            hints.you_parts.append(p.key)
    for a in attrs:
        if a.removed:
            hints.removed.append(a.key)
        elif a.source in USER_SOURCES:
            hints.you_dimensions.append(a.key)
    item = items_repo.get(session, item_id)
    if item is not None and item.content_type_locked:
        hints.content_type = item.content_type
    if item is not None and item.parent_item_id:
        parent_rows = session.scalars(
            select(ItemAttribute)
            .where(ItemAttribute.item_id == item.parent_item_id, ItemAttribute.removed.is_(False))
            .order_by(ItemAttribute.key)
        )
        hints.parent_dimensions = [
            {"key": r.key, "label": r.label, "type": r.dim_type, "part": r.part, "kind": r.kind}
            for r in parent_rows
        ]
    return hints


def _count_text(n: int, total: int) -> str:
    return f"{n} of {total}"


def _option_lines(session: Session, board_id: str) -> list[str]:
    q = (
        select(Exploration, ExploreOption)
        .join(ExploreOption, ExploreOption.exploration_id == Exploration.id)
        .where(Exploration.board_id == board_id, ExploreOption.status.in_(("kept", "dismissed")))
        .order_by(Exploration.id, ExploreOption.created_at, ExploreOption.id)
    )
    by_label: dict[str, dict[str, list[str]]] = {}
    for expl, opt in session.execute(q).all():
        row = session.scalar(
            select(ItemAttribute).where(
                ItemAttribute.item_id == expl.item_id, ItemAttribute.key == expl.key
            )
        )
        label = row.label if row is not None else expl.key
        by_label.setdefault(label, {"kept": [], "dismissed": []})[opt.status].append(opt.name)
    lines = []
    for label in sorted(by_label):
        kept, dismissed = by_label[label]["kept"], by_label[label]["dismissed"]
        parts = []
        if kept:
            parts.append(f"Kept for {label}: {', '.join(kept)}")
        if dismissed:
            parts.append(
                f"not: {', '.join(dismissed)}"
                if kept
                else f"Not for {label}: " + ", ".join(dismissed)
            )
        lines.append("; ".join(parts))
    return lines


def refresh_learned(session: Session, board_id: str) -> list[str]:
    """Rebuild the board's learned lines from its profile and the options the user kept or
    dismissed. No model call. Saves `learned_json`; publishes `board.learned` if it changed."""
    board = boards_repo.get(session, board_id)
    if board is None:
        return []
    items = items_repo.list_active(session, board_id, include_staged=False)
    attrs = {i.id: attrs_repo.for_item(session, i.id) for i in items}
    profile = compute_profile(items, attrs, None, {})
    lines: list[str] = []
    for s in profile.signals:
        n = round(s.consistency * s.n_known)
        lines.append(f"{s.label}: {s.modal_value} · {_count_text(n, s.n_known)}")
    for t in profile.tensions:
        dist = profile.attributes[t.key].distribution
        lines.append(
            f"{t.label}: "
            + " · ".join(
                f"{v} {dist.get(v, round(sh * profile.attributes[t.key].n_known))}"
                for v, sh in zip(t.values, t.shares, strict=True)
            )
        )
    lines.extend(_option_lines(session, board_id))
    lines = lines[:MAX_LEARNED]
    if lines != (board.learned_json or []):
        board.learned_json = lines
        session.flush()
        after_commit(
            session, partial(events.publish, board_id, "board.learned", {"learned": lines})
        )
    return lines


@dataclass(frozen=True)
class Offer:
    label: str
    dim_type: str
    kind: str
    count: int
    total: int


def _norm(label: str) -> str:
    return " ".join(label.lower().split())


def _entry_id(e: dict[str, Any]) -> tuple[str, str, str]:
    return (_norm(str(e.get("label", ""))), str(e.get("dim_type", "")), str(e.get("kind", "")))


def dimension_offers(session: Session, board_id: str) -> list[Offer]:
    """Dimensions that recur on two or more items and are not yet a board dimension nor declined."""
    board = boards_repo.get(session, board_id)
    if board is None:
        return []
    known = {_entry_id(e) for e in (board.dimensions_json or [])}
    known |= {_entry_id(e) for e in (board.declined_json or [])}
    groups: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    names: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    for item, a in _current_rows(session, board_id):
        gid = (
            _norm(a.label),
            a.dim_type,
            a.kind,
            (a.part or "") if a.dim_type == "physical" else "",
        )
        groups[gid].add(item.id)
        names[gid][a.label] += 1
    total = len({i.id for i, _ in _current_rows(session, board_id)})
    merged: dict[tuple[str, str, str], Offer] = {}
    for gid in sorted(groups):
        n = len(groups[gid])
        oid = gid[:3]
        if n < OFFER_MIN_ITEMS or oid in known:
            continue
        label = min(names[gid].items(), key=lambda kv: (-kv[1], kv[0]))[0]
        prev = merged.get(oid)
        if prev is None or n > prev.count:
            merged[oid] = Offer(label, gid[1], gid[2], n, total)
    return sorted(merged.values(), key=lambda o: (-o.count, o.label.lower()))


def _append(
    session: Session, board_id: str, column: str, label: str, dim_type: str, kind: str
) -> None:
    board = boards_repo.get(session, board_id)
    if board is None:
        return
    entry = {"label": label, "dim_type": dim_type, "kind": kind}
    current = list(getattr(board, column) or [])
    if _entry_id(entry) not in {_entry_id(e) for e in current}:
        setattr(board, column, [*current, entry])
        session.flush()


def accept_offer(session: Session, board_id: str, label: str, dim_type: str, kind: str) -> None:
    _append(session, board_id, "dimensions_json", label, dim_type, kind)


def decline_offer(session: Session, board_id: str, label: str, dim_type: str, kind: str) -> None:
    _append(session, board_id, "declined_json", label, dim_type, kind)
