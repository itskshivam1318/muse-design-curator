"""Board-driven lens selection: curated when the domain is known, else proposed then confirmed.

Both kinds are pruned per board: a SAM part found in under half of up to 10 board images falls back
to whole-image grounding in that board's lens version (noted in `lens.notes`).
"""

import io
import logging
from functools import partial
from typing import Any

import numpy as np
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import events, jobs
from app.api.schemas import board_to_dict
from app.board.votes import ambiguous_candidates, domain_votes
from app.config import get_settings
from app.db.models import Board, BoardItem, Lens
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.repos import lenses as lenses_repo
from app.db.repos import masks as masks_repo
from app.db.session import after_commit
from app.domain.lens import LensSpec, load_curated_lens, validate_lens
from app.errors import AppError
from app.providers import get_reasoning, get_segmentation
from app.providers.reliability import ModelError
from app.storage import files

log = logging.getLogger(__name__)

MIN_ITEMS = 5
MAX_SAMPLE = 20
MAX_PRUNE_IMAGES = 10
MIN_PART_HIT_RATE = 0.5
MIN_PRUNE_IMAGES = MIN_ITEMS  # a curated lens is judged on at least this many board images
CHECKED_NOTE = "Parts checked against"
FALLBACK_DOMAIN = "custom"
LENS_ITEM_STATUSES = ("completed", "pending_lens")


def curated_lens(domain: str) -> LensSpec | None:
    return load_curated_lens(domain, get_settings().SHAPE_KIND_ENABLED)


def _require_board(session: Session, board_id: str) -> Board:
    board = boards_repo.get(session, board_id)
    if board is None:
        raise AppError(404, "BOARD_NOT_FOUND", "Board not found")
    return board


def _eligible(session: Session, board_id: str) -> list[BoardItem]:
    return [
        i for i in items_repo.list_active(session, board_id) if i.parse_status in LENS_ITEM_STATUSES
    ]


def _domain_key(board: Board) -> str:
    return board.domain or FALLBACK_DOMAIN


def _next_version(session: Session, board_id: str, domain: str) -> int:
    cur = lenses_repo.latest(session, board_id, domain)
    return (cur.version if cur else 0) + 1


def board_lens_row(session: Session, board: Board) -> Lens | None:
    """The lens row the board currently points at, else its newest row."""
    if board.lens_id:
        row = lenses_repo.get(session, board.lens_id)
        if row is not None:
            return row
    q = (
        select(Lens)
        .where(Lens.board_id == board.id)
        .order_by(Lens.created_at.desc(), Lens.version.desc())
    )
    return session.scalars(q).first()


def ensure_board_lens(session: Session, board_id: str, *, prune: bool = True) -> LensSpec | None:
    """The board's lens, attaching the curated one for its domain (or proposing one) if needed.

    A curated lens is pruned on the board's images when it is attached; with fewer than
    MIN_PRUNE_IMAGES images (or `prune=False`, for request handlers) it is attached as shipped and
    pruned by a later call, once. Pruning runs SAM through the mask cache the items' parsing uses.
    """
    board = _require_board(session, board_id)
    if board.lens_id:
        row = lenses_repo.get(session, board.lens_id)
        if row is not None:
            spec = LensSpec.model_validate(row.spec_json)
            if prune and row.origin == "curated" and needs_part_check(spec):
                pruned = _prune_curated(session, board, spec)
                if pruned is not None:
                    return _attach_curated(session, board, pruned, current=row.id)
            return spec
    if board.domain:
        curated = curated_lens(board.domain)
        if curated is not None:
            spec = curated
            if prune and needs_part_check(curated):
                spec = _prune_curated(session, board, curated) or curated
            return _attach_curated(session, board, spec, current=None)
    if lenses_repo.latest(session, board.id, _domain_key(board)) is not None:
        return None  # already proposed, awaiting confirmation
    eligible = _eligible(session, board.id)
    if len(eligible) < MIN_ITEMS:
        return None
    if not board.domain:
        candidates = ambiguous_candidates(domain_votes(session, eligible))
        if candidates:
            raise AppError(
                409, "LENS_AMBIGUOUS", "Board mixes several domains", {"candidates": candidates}
            )
    propose_lens(session, board.id)
    return None


AUTO_MIN_EMBEDDED = 3


def auto_attach_domain(session: Session, board_id: str) -> str | None:
    """Give an Auto board (no domain) the curated domain its items clearly vote for.

    A clear winner: not ambiguous, at least AUTO_MIN_EMBEDDED embedded items, and a curated lens.
    A domain the user set is never overridden. Returns the new domain, else None.
    """
    board = _require_board(session, board_id)
    if board.domain:
        return None
    embedded = [i for i in items_repo.list_active(session, board.id) if i.embedding_json]
    if len(embedded) < AUTO_MIN_EMBEDDED:
        return None
    votes = domain_votes(session, embedded)
    if not votes or ambiguous_candidates(votes):
        return None
    winner = max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    if curated_lens(winner) is None:
        return None
    boards_repo.update(session, board.id, domain=winner)
    ensure_board_lens(session, board.id)  # attaches the curated lens, queues pending_lens items
    data = {"board": board_to_dict(board)}
    after_commit(session, lambda: events.publish(board.id, "board.updated", data))
    return winner


def sample_diverse(items: list[BoardItem], k: int = MAX_SAMPLE) -> list[BoardItem]:
    """Greedy farthest-point sampling, seeded by the item farthest from the centroid."""
    embedded = [i for i in items if i.embedding_json]
    if len(embedded) <= k:
        rest = [i for i in items if not i.embedding_json]
        return (embedded + rest)[:k]
    m = np.asarray([i.embedding_json for i in embedded], dtype=np.float64)
    first = int(np.argmax(np.linalg.norm(m - m.mean(axis=0), axis=1)))
    chosen = [first]
    dist = np.linalg.norm(m - m[first], axis=1)
    while len(chosen) < k:
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, np.linalg.norm(m - m[nxt], axis=1))
    return [embedded[i] for i in chosen]


def _image_bytes(item: BoardItem) -> bytes | None:
    rel = item.storage_path if item.kind == "image" else item.thumb_path
    rel = rel or item.thumb_path
    if not rel:
        return None
    path = files.abs_path(rel)
    return path.read_bytes() if path.is_file() else None


def _found(session: Session | None, seg: Any, image: bytes, sha: str, prompt: str) -> bool:
    """Whether SAM finds the part; with a session, through the (image sha, prompt) mask cache."""
    if session is None:
        return bool(seg.localize(image, sha, prompt).found)
    from app.extraction.service import _part_mask  # the extraction service imports this module

    row = masks_repo.get(session, sha, prompt)
    if row is None:
        with Image.open(io.BytesIO(image)) as im:
            width, height = im.size
        _part_mask(session, seg, image, sha, prompt, (height, width))  # commits the new row
        row = masks_repo.get(session, sha, prompt)
    return bool(row is not None and row.found)


def prune_parts(lens: LensSpec, images: list[bytes], session: Session | None = None) -> LensSpec:
    """Parts SAM finds in under half the sample images fall back to whole-image grounding."""
    sample = images[:MAX_PRUNE_IMAGES]
    if not sample or not lens.parts:
        return lens
    seg = get_segmentation(get_settings())
    shas = [files.sha256_hex(b) for b in sample]
    parts = []
    notes = list(lens.notes)
    for part in lens.parts:
        if part.grounding != "sam":
            parts.append(part)
            continue
        hits = sum(_found(session, seg, b, s, part.sam_prompt) for b, s in zip(sample, shas))
        if hits / len(sample) < MIN_PART_HIT_RATE:
            parts.append(part.model_copy(update={"grounding": "whole_image"}))
            notes.append(
                f"Part {part.id} was found in {hits} of {len(sample)} sample images; "
                "using the whole image instead."
            )
        else:
            parts.append(part)
    return lens.model_copy(update={"parts": parts, "notes": notes})


def needs_part_check(spec: LensSpec) -> bool:
    """A lens with SAM parts that has not been checked against its board's images yet."""
    return any(p.grounding == "sam" for p in spec.parts) and not any(
        n.startswith(CHECKED_NOTE) for n in spec.notes
    )


def _board_images(session: Session, board_id: str) -> list[bytes]:
    sampled = sample_diverse(items_repo.list_active(session, board_id), MAX_PRUNE_IMAGES)
    return [b for b in (_image_bytes(i) for i in sampled) if b is not None]


def _prune_curated(session: Session, board: Board, spec: LensSpec) -> LensSpec | None:
    """The curated lens pruned on this board's images; None when there are too few to judge yet
    (or SAM failed: a later call tries again)."""
    images = _board_images(session, board.id)
    if len(images) < MIN_PRUNE_IMAGES:
        return None
    try:
        pruned = prune_parts(spec, images, session=session)
    except ModelError as exc:
        log.warning("pruning the curated lens of board %s failed: %s", board.id, exc.code)
        return None
    note = f"{CHECKED_NOTE} {len(images)} board images."
    return pruned.model_copy(update={"notes": [*pruned.notes, note]})


def _attach_curated(
    session: Session, board: Board, spec: LensSpec, *, current: str | None
) -> LensSpec:
    """Save `spec` as the board's next curated lens version, unless another worker attached a
    lens while this one was pruning (pruning commits mask rows and can take a while)."""
    now = session.scalar(select(Board.lens_id).where(Board.id == board.id))
    if now is not None and now != current:
        row = lenses_repo.get(session, now)
        if row is not None:
            board.lens_id = now
            return LensSpec.model_validate(row.spec_json)
    row = lenses_repo.save(
        session, board.id, spec.domain, "curated", spec.model_dump(mode="json"),
        status="confirmed",
    )  # fmt: skip
    board.lens_id = row.id
    _release_pending(session, board.id)
    return spec


PRUNE_JOB = "prune_board_lens"


def prune_board_lens_job(board_id: str) -> None:
    """Background job: prune the board's curated lens if it has not been checked yet (boards whose
    lens was attached before per-board pruning, or attached with too few images)."""
    from app.api import deps

    with deps._factory()() as session:
        try:
            ensure_board_lens(session, board_id, prune=True)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("pruning the lens of board %s failed", board_id)


jobs.register(PRUNE_JOB, prune_board_lens_job, queue="background")


def propose_lens(session: Session, board_id: str) -> LensSpec:
    return LensSpec.model_validate(propose_lens_row(session, board_id).spec_json)


def propose_lens_row(session: Session, board_id: str) -> Lens:
    board = _require_board(session, board_id)
    eligible = _eligible(session, board.id)
    if len(eligible) < MIN_ITEMS:
        raise AppError(
            409, "LENS_NOT_ENOUGH_ITEMS", f"A lens needs at least {MIN_ITEMS} parsed items"
        )
    sampled = sample_diverse(eligible, MAX_SAMPLE)
    images = [b for b in (_image_bytes(i) for i in sampled) if b is not None]
    settings = get_settings()
    raw = get_reasoning(settings).propose_lens(
        images, board.context or "", LensSpec.model_json_schema()
    )
    domain = _domain_key(board)
    version = _next_version(session, board.id, domain)
    try:
        spec = LensSpec.model_validate(
            {**raw, "id": f"{domain}@{version}", "domain": domain, "origin": "proposed"}
        )
        validate_lens(spec, settings.SHAPE_KIND_ENABLED)
    except (ValidationError, ValueError, TypeError) as exc:
        log.warning("lens proposal rejected: %s", exc)
        raise AppError(502, "LENS_PROPOSAL_INVALID", "The proposed lens was not valid") from exc
    spec = prune_parts(spec, images)
    row = lenses_repo.save(
        session, board.id, domain, "proposed", spec.model_dump(mode="json"), status="proposed"
    )
    payload = {"lens_id": row.id, "version": row.version}
    after_commit(session, lambda: events.publish(board.id, "lens.proposed", payload))
    return row


def _release_pending(session: Session, board_id: str) -> None:
    for item in items_repo.list_active(session, board_id):
        if item.parse_status == "pending_lens":
            item.parse_status = "pending"
            session.flush()
            after_commit(session, partial(jobs.enqueue, "parse_item", item_id=item.id))


def confirm_lens(session: Session, board_id: str, spec: LensSpec | None) -> Lens:
    board = _require_board(session, board_id)
    current = board_lens_row(session, board)
    if spec is None:
        if current is None:
            raise AppError(404, "LENS_NOT_FOUND", "No lens to confirm")
        current.status = "confirmed"
        row = current
    else:
        domain = current.domain if current is not None else spec.domain
        version = _next_version(session, board.id, domain)
        edited = spec.model_copy(
            update={"id": f"{domain}@{version}", "domain": domain, "origin": "edited"}
        )
        try:
            edited = validate_lens(
                LensSpec.model_validate(edited.model_dump()), get_settings().SHAPE_KIND_ENABLED
            )
        except ValueError as exc:
            raise AppError(400, "VALIDATION_ERROR", str(exc)) from exc
        row = lenses_repo.save(
            session, board.id, domain, "edited", edited.model_dump(mode="json"), status="confirmed"
        )
    board.lens_id = row.id
    session.flush()
    _release_pending(session, board.id)
    return row


def lens_to_dict(row: Lens) -> dict[str, Any]:
    return {
        "id": row.id, "board_id": row.board_id, "domain": row.domain, "version": row.version,
        "origin": row.origin, "status": row.status, "spec": row.spec_json,
        "created_at": row.created_at,
    }  # fmt: skip
