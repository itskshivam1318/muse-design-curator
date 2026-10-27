from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.ids import PREFIXES, new_id, now_iso


class Base(DeclarativeBase):
    pass


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _id(kind: str) -> Mapped[str]:
    return mapped_column(String, primary_key=True, default=lambda: new_id(PREFIXES[kind]))


def _created() -> Mapped[str]:
    return mapped_column(String, default=now_iso)


def _json(nullable: bool = True) -> Mapped[Any]:
    return mapped_column(JSON, nullable=nullable)


class Board(Base):
    __tablename__ = "boards"
    id: Mapped[str] = _id("board")
    title: Mapped[str] = mapped_column(String)
    context: Mapped[str] = mapped_column(String, default="")
    domain: Mapped[str | None] = mapped_column(String)
    lens_id: Mapped[str | None] = mapped_column(String)  # no FK: lenses.board_id references boards
    created_at: Mapped[str] = _created()
    updated_at: Mapped[str] = mapped_column(String, default=now_iso, onupdate=now_iso)


ITEM_KINDS = ("image", "video", "link")
ORIGINS = ("upload", "drop", "paste", "link", "extension", "candidate", "seed")
RIGHTS = ("user_supplied", "licensed")
PARSE_STATUS = ("pending", "pending_lens", "processing", "completed", "failed")
ROLES = ("reference", "counter_example")


class CorpusItem(Base):
    __tablename__ = "corpus_items"
    id: Mapped[str] = _id("corpus")
    domain: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)
    landing_url: Mapped[str] = mapped_column(String)
    image_url: Mapped[str] = mapped_column(String)
    local_path: Mapped[str | None] = mapped_column(String)
    creator_name: Mapped[str | None] = mapped_column(String)
    license_code: Mapped[str] = mapped_column(String)
    license_url: Mapped[str | None] = mapped_column(String)
    attribution_text: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[str] = mapped_column(String, default=now_iso)
    sha256: Mapped[str | None] = mapped_column(String, index=True)
    dhash: Mapped[str | None] = mapped_column(String)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    embedding_row: Mapped[int | None] = mapped_column(Integer)
    indexing_status: Mapped[str] = mapped_column(String, default="pending")
    provenance_status: Mapped[str] = mapped_column(String, default="valid")
    provenance_issue: Mapped[str | None] = mapped_column(String)
    # 'quick' = embedding and palette only (live search); 'full' or NULL = fully indexed
    index_depth: Mapped[str | None] = mapped_column(String)
    palette_json: Mapped[Any] = _json()
    __table_args__ = (
        UniqueConstraint("source", "source_id"),
        CheckConstraint(_in("indexing_status", ("pending", "indexed", "failed"))),
        CheckConstraint(_in("provenance_status", ("valid", "invalid"))),
    )


class CorpusAttribute(Base):
    __tablename__ = "corpus_attributes"
    item_id: Mapped[str] = mapped_column(ForeignKey("corpus_items.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[Any] = _json()
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[Any] = _json()
    measured_json: Mapped[Any] = _json()


class BoardItem(Base):
    __tablename__ = "board_items"
    id: Mapped[str] = _id("item")
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String)
    sha256: Mapped[str | None] = mapped_column(String)
    storage_path: Mapped[str | None] = mapped_column(String)
    thumb_path: Mapped[str | None] = mapped_column(String)
    mime: Mapped[str | None] = mapped_column(String)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    original_filename: Mapped[str | None] = mapped_column(String)
    source_url: Mapped[str | None] = mapped_column(String)
    page_url: Mapped[str | None] = mapped_column(String)
    page_title: Mapped[str | None] = mapped_column(String)
    creator_handle: Mapped[str | None] = mapped_column(String)
    captured_at: Mapped[str] = mapped_column(String, default=now_iso)
    rights_status: Mapped[str] = mapped_column(String, default="user_supplied")
    corpus_item_id: Mapped[str | None] = mapped_column(ForeignKey("corpus_items.id"))
    parent_item_id: Mapped[str | None] = mapped_column(ForeignKey("board_items.id"))
    parse_status: Mapped[str] = mapped_column(String, default="pending")
    parse_error_code: Mapped[str | None] = mapped_column(String)
    parse_attempts: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String, default="reference")
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    w: Mapped[float] = mapped_column(Float, default=0)
    h: Mapped[float] = mapped_column(Float, default=0)
    z: Mapped[int] = mapped_column(Integer, default=0)
    embedding_json: Mapped[Any] = _json()
    embedder_id: Mapped[str | None] = mapped_column(String)
    palette_json: Mapped[Any] = _json()
    removed_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = _created()
    __table_args__ = (
        CheckConstraint(_in("kind", ITEM_KINDS), name="ck_item_kind"),
        CheckConstraint(_in("origin", ORIGINS), name="ck_item_origin"),
        CheckConstraint(_in("rights_status", RIGHTS), name="ck_item_rights"),
        CheckConstraint(_in("parse_status", PARSE_STATUS), name="ck_item_parse_status"),
        CheckConstraint(_in("role", ROLES), name="ck_item_role"),
        CheckConstraint(
            "(rights_status = 'licensed') = (corpus_item_id IS NOT NULL)",
            name="ck_item_licensed_iff_corpus",
        ),
        Index(
            "uq_board_items_active_sha256",
            "board_id",
            "sha256",
            unique=True,
            sqlite_where=text("removed_at IS NULL AND sha256 IS NOT NULL"),
        ),
    )


class ItemFrame(Base):
    __tablename__ = "item_frames"
    id: Mapped[str] = _id("frame")
    item_id: Mapped[str] = mapped_column(ForeignKey("board_items.id"), index=True)
    t_ms: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    chosen: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemAttribute(Base):
    __tablename__ = "item_attributes"
    id: Mapped[str] = _id("attribute")
    item_id: Mapped[str] = mapped_column(ForeignKey("board_items.id"))
    key: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    part: Mapped[str | None] = mapped_column(String)
    value_json: Mapped[Any] = _json()
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    source_detail: Mapped[str] = mapped_column(String, default="")
    evidence_json: Mapped[Any] = _json()
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_value_json: Mapped[Any] = _json()
    model_confidence: Mapped[float | None] = mapped_column(Float)
    measured_json: Mapped[Any] = _json()
    updated_at: Mapped[str] = mapped_column(String, default=now_iso, onupdate=now_iso)
    __table_args__ = (UniqueConstraint("item_id", "key"),)


class AttributeEvent(Base):
    __tablename__ = "attribute_events"
    id: Mapped[str] = _id("event")
    item_id: Mapped[str] = mapped_column(ForeignKey("board_items.id"), index=True)
    key: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    before_json: Mapped[Any] = _json()
    after_json: Mapped[Any] = _json()
    created_at: Mapped[str] = _created()
    __table_args__ = (
        CheckConstraint(_in("actor", ("user", "model"))),
        CheckConstraint(
            _in(
                "action",
                ("extracted", "model_suppressed", "edited", "confirmed", "disabled", "enabled"),
            )
        ),
    )


class Lens(Base):
    __tablename__ = "lenses"
    id: Mapped[str] = _id("lens")
    board_id: Mapped[str | None] = mapped_column(ForeignKey("boards.id"))
    domain: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="proposed")
    spec_json: Mapped[Any] = _json(nullable=False)
    created_at: Mapped[str] = _created()
    __table_args__ = (
        UniqueConstraint("board_id", "domain", "version"),
        Index(
            "uq_lenses_curated_domain_version",
            "domain",
            "version",
            unique=True,
            sqlite_where=text("board_id IS NULL"),
        ),
        CheckConstraint(_in("status", ("proposed", "confirmed"))),
    )


class PartMask(Base):
    __tablename__ = "part_masks"
    image_sha256: Mapped[str] = mapped_column(String, primary_key=True)
    sam_prompt: Mapped[str] = mapped_column(String, primary_key=True)
    found: Mapped[bool] = mapped_column(Boolean)
    bbox_json: Mapped[Any] = _json()
    mask_path: Mapped[str | None] = mapped_column(String)
    score: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = _created()


class BoardProfile(Base):
    __tablename__ = "board_profiles"
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_json: Mapped[Any] = _json(nullable=False)
    computed_at: Mapped[str] = mapped_column(String, default=now_iso)


class VariationRun(Base):
    __tablename__ = "variation_runs"
    id: Mapped[str] = _id("run")
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    source_item_id: Mapped[str] = mapped_column(ForeignKey("board_items.id"))
    lens_id: Mapped[str] = mapped_column(ForeignKey("lenses.id"))
    target_key: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    target_values_json: Mapped[Any] = _json(nullable=False)
    nudge_json: Mapped[Any] = _json()
    protected_keys_json: Mapped[Any] = _json(nullable=False)
    source_snapshot_json: Mapped[Any] = _json(nullable=False)
    board_profile_version: Mapped[int] = mapped_column(Integer)
    ranking_version: Mapped[str] = mapped_column(String)
    ranking_config_json: Mapped[Any] = _json(nullable=False)
    validator_version: Mapped[str] = mapped_column(String)
    providers_json: Mapped[Any] = _json(nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued")
    progress_json: Mapped[Any] = _json()
    summary_json: Mapped[Any] = _json()
    error_code: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[str] = _created()
    completed_at: Mapped[str | None] = mapped_column(String)
    # heartbeat: stamped by every progress write; NULL while the run has never started
    updated_at: Mapped[str | None] = mapped_column(String)
    # the demo visitor charged for this run (refunded if it is interrupted)
    client_ip: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint(
            _in("status", ("queued", "retrieving", "validating", "completed", "failed"))
        ),
    )


class RunCandidate(Base):
    __tablename__ = "run_candidates"
    id: Mapped[str] = _id("candidate")
    run_id: Mapped[str] = mapped_column(ForeignKey("variation_runs.id"), index=True)
    corpus_item_id: Mapped[str] = mapped_column(ForeignKey("corpus_items.id"))
    state: Mapped[str] = mapped_column(String, default="retrieved")
    excluded_reason: Mapped[str | None] = mapped_column(String)
    excluded_detail: Mapped[str | None] = mapped_column(String)
    scores_json: Mapped[Any] = _json()
    rank: Mapped[int | None] = mapped_column(Integer)
    observed_target_json: Mapped[Any] = _json()
    # 'live' = found by this run's live source search; NULL = from the corpus
    origin: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        UniqueConstraint("run_id", "corpus_item_id"),
        CheckConstraint(
            _in(
                "state",
                ("retrieved", "excluded", "validating", "validated", "uncertain", "rejected"),
            )
        ),
    )


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[str] = _id("validation")
    run_candidate_id: Mapped[str] = mapped_column(ForeignKey("run_candidates.id"), index=True)
    check: Mapped[str] = mapped_column(String)
    attribute_key: Mapped[str | None] = mapped_column(String)
    verdict: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[Any] = _json()
    validator_version: Mapped[str] = mapped_column(String)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = _id("decision")
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    run_id: Mapped[str] = mapped_column(String)
    run_candidate_id: Mapped[str] = mapped_column(String, index=True)
    corpus_item_id: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    reason_code: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    item_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = _created()
    __table_args__ = (CheckConstraint(_in("decision", ("keep", "reject"))),)


class ModelCache(Base):
    __tablename__ = "model_cache"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    response_json: Mapped[Any] = _json(nullable=False)
    created_at: Mapped[str] = _created()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    route: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[Any] = _json(nullable=False)
    created_at: Mapped[str] = _created()


class ExtensionToken(Base):
    __tablename__ = "extension_tokens"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = _created()
    last_used_at: Mapped[str | None] = mapped_column(String)
