"""Ordered exclusions applied to the pool, each with a distinct reason and a plain detail."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.corpus.hashing import dhash as compute_dhash
from app.corpus.hashing import hamming
from app.corpus.subject import ABSENT, subject_status
from app.domain.variation import VariationSpec
from app.measure.palette import named_lab
from app.retrieval.config import RankingConfig
from app.retrieval.pool import PoolItem
from app.storage import files
from app.validation.comparators import AttrValue, Verdict, compare

MIN_EDGE = 256


@dataclass
class SourceItem:
    sha256: str | None = None
    dhash: str | None = None
    corpus_item_id: str | None = None
    storage_path: str | None = None
    attrs: dict[str, AttrValue] = field(default_factory=dict)


@dataclass(frozen=True)
class OnBoard:
    """Corpus ids and hashes of the board's active items (the source item left out).

    `board_item_ids` maps either a corpus id or a sha256 to the matching board item id.
    """

    corpus_item_ids: frozenset[str] = frozenset()
    sha256s: frozenset[str] = frozenset()
    board_item_ids: Mapping[str, str] = field(default_factory=dict)


def on_board_from_items(items: Iterable[Any], source_item_id: str | None = None) -> OnBoard:
    ids: set[str] = set()
    shas: set[str] = set()
    owner: dict[str, str] = {}
    for it in items:
        if it.removed_at is not None or it.id == source_item_id:
            continue
        if it.corpus_item_id:
            ids.add(it.corpus_item_id)
            owner.setdefault(it.corpus_item_id, it.id)
        if it.sha256:
            shas.add(it.sha256)
            owner.setdefault(it.sha256, it.id)
    return OnBoard(frozenset(ids), frozenset(shas), owner)


def source_from_board_item(
    board_item: Any, attrs: dict[str, AttrValue] | None = None
) -> SourceItem:
    """Board items store no dHash; compute it from the stored original when it can be read."""
    dh: str | None = None
    if board_item.storage_path:
        p = files.abs_path(board_item.storage_path)
        if p.is_file():
            try:
                dh = compute_dhash(p.read_bytes())
            except (
                OSError,
                ValueError,
            ):  # unreadable image: duplicates are then judged by sha256 only
                dh = None
    return SourceItem(
        board_item.sha256, dh, board_item.corpus_item_id, board_item.storage_path, attrs or {}
    )


def _exclude(item: PoolItem, reason: str, **detail: Any) -> dict[str, Any]:
    return {"item": item, "reason": reason, "detail": detail}


def _unusable(item: PoolItem) -> str | None:
    c = item.item
    if c.indexing_status != "indexed":
        return f"indexing {c.indexing_status}"
    if not c.local_path or not files.abs_path(c.local_path).is_file():
        return "file missing"
    if c.width is None or c.height is None or min(c.width, c.height) < MIN_EDGE:
        return f"shortest edge below {MIN_EDGE}px"
    return None


def apply_exclusions(
    pool: list[PoolItem],
    spec: VariationSpec,
    source_item: SourceItem,
    cfg: RankingConfig,
    on_board: OnBoard | None = None,
) -> tuple[list[PoolItem], list[dict[str, Any]]]:
    kept: list[PoolItem] = []
    excluded: list[dict[str, Any]] = []
    tspec, mode = spec.target_spec, spec.request.mode
    src_target = source_item.attrs.get(tspec.key) or AttrValue(spec.target_value, 1.0, "confirmed")
    for p in sorted(pool, key=lambda x: (-x.relevance, x.item.id)):
        c = p.item
        if (source_item.sha256 and c.sha256 == source_item.sha256) or (
            source_item.corpus_item_id and c.id == source_item.corpus_item_id
        ):
            excluded.append(_exclude(p, "source", detail="same image as the source"))
            continue
        if on_board and (c.id in on_board.corpus_item_ids or c.sha256 in on_board.sha256s):
            owner = on_board.board_item_ids.get(c.id) or on_board.board_item_ids.get(c.sha256 or "")
            excluded.append(_exclude(p, "on_board", **({"board_item_id": owner} if owner else {})))
            continue
        if c.provenance_status == "invalid":
            excluded.append(_exclude(p, "provenance", issue=c.provenance_issue))
            continue
        why = _unusable(p)
        if why:
            excluded.append(_exclude(p, "unusable", problem=why))
            continue
        if subject_status(a.value for a in p.attrs.values()) == ABSENT:
            readable = sum(a.value is not None for a in p.attrs.values())
            excluded.append(_exclude(p, "not_subject", readable=readable, of=len(p.attrs)))
            continue
        if c.dhash:
            near = None
            if source_item.dhash and hamming(c.dhash, source_item.dhash) <= (
                cfg.duplicate_dhash_distance
            ):
                near = "source"
            else:
                for k in kept:
                    if k.item.dhash and hamming(c.dhash, k.item.dhash) <= (
                        cfg.duplicate_dhash_distance
                    ):
                        near = k.item.id
                        break
            if near:
                excluded.append(_exclude(p, "duplicate", duplicate_of=near))
                continue
        broken = None
        for prot in spec.protected:
            src = source_item.attrs.get(prot.key) or AttrValue(prot.value, 1.0, "confirmed")
            cand = p.attrs.get(prot.key)
            if cand and compare(prot.spec, cand, src, cfg) == "different":
                broken = (prot.key, cand.value, src.value)
                break
        if broken:
            excluded.append(
                _exclude(p, "hard_constraint", attribute=broken[0], candidate=broken[1],
                         source=broken[2])
            )  # fmt: skip
            continue
        cand_t = p.attrs.get(tspec.key)
        if mode == "avoid" and cand_t:
            hit = next((v for v in spec.values if same_as_value(tspec, cand_t, v, cfg)), None)
            if hit is not None:
                excluded.append(
                    _exclude(p, "avoided_value", attribute=tspec.key, candidate=cand_t.value,
                             avoided=hit)
                )  # fmt: skip
                continue
        if mode == "explore" and cand_t and compare(tspec, cand_t, src_target, cfg) == "same":
            excluded.append(
                _exclude(p, "no_target_change", attribute=tspec.key, candidate=cand_t.value,
                         source=src_target.value)
            )  # fmt: skip
            continue
        kept.append(p)
    return kept, excluded


def value_verdict(tspec: Any, cand: AttrValue, value: Any, cfg: RankingConfig) -> Verdict:
    """Compare a candidate attribute with a literal value (colour names resolve to Lab)."""
    measured = None
    if tspec.kind == "color":
        lab = named_lab(str(value))
        measured = {"lab": list(lab)} if lab else None
    ref = AttrValue(value, 1.0, "confirmed", measured)
    return compare(tspec, cand, ref, cfg)


def same_as_value(tspec: Any, cand: AttrValue, value: Any, cfg: RankingConfig) -> bool:
    return value_verdict(tspec, cand, value, cfg) == "same"
