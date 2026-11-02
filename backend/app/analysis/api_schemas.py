"""Request and response shapes of the analysis routes, and the views built from stored rows."""

from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.context import USER_SOURCES, dimension_offers
from app.analysis.spec import dimension_type
from app.analysis.types import AttrKind, DimType, Region, RegionKind
from app.db.models import BoardItem, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo


class PartView(BaseModel):
    key: str
    label: str
    region_kind: RegionKind
    region: list[float] | list[int] | None = None  # as stored: a mask part holds its box
    mask_url: str | None = None  # set once the part has a located mask
    source: str


class DimensionView(BaseModel):
    key: str
    label: str
    type: DimType
    part: str | None = None
    prompt: str | None = None
    kind: AttrKind
    value: Any = None
    confidence: float
    source: Literal["ai", "you"]  # the person's own rows are "you"; model and measured are "ai"
    status: str  # "stale" for a dimension the latest analysis no longer found


class AnalysisView(BaseModel):
    content_type: str | None
    parse_status: str
    parts: list[PartView]
    dimensions: list[DimensionView]


class PartCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    region: Region | None = None


class PartPatch(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class DimensionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    type: DimType
    part: str | None = None
    prompt: str | None = Field(default=None, max_length=300)
    kind: AttrKind = "text"


class DimensionPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    type: DimType | None = None
    part: str | None = Field(
        default=None, description="The part a physical dimension reads. None means no change."
    )
    prompt: str | None = Field(default=None, max_length=300)


class OfferBody(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    dim_type: DimType
    kind: AttrKind
    part: str | None = None


def part_view(p: ItemPart) -> PartView:
    return PartView(
        key=p.key, label=p.label, region_kind=p.region_kind,  # type: ignore[arg-type]
        region=p.region_json, mask_url=f"/api/media/{p.mask_path}" if p.mask_path else None,
        source=p.source,
    )  # fmt: skip


def dimension_view(r: ItemAttribute) -> DimensionView:
    return DimensionView.model_validate(
        {
            "key": r.key, "label": r.label, "type": dimension_type(r), "part": r.part,
            "prompt": r.prompt, "kind": r.kind, "value": r.value_json,
            "confidence": r.confidence, "source": "you" if r.source in USER_SOURCES else "ai",
            "status": r.status,
        }
    )  # fmt: skip


def analysis_view(session: Session, item: BoardItem) -> AnalysisView:
    """The item's parts and dimensions; removed ones are left out, stale dimensions marked."""
    parts = session.scalars(
        select(ItemPart)
        .where(ItemPart.item_id == item.id, ItemPart.removed.is_(False))
        .order_by(ItemPart.created_at, ItemPart.key)
    )
    return AnalysisView(
        content_type=item.content_type, parse_status=item.parse_status,
        parts=[part_view(p) for p in parts],
        dimensions=[
            dimension_view(r) for r in attrs_repo.for_item(session, item.id) if not r.removed
        ],
    )  # fmt: skip


def context_view(session: Session, board_id: str) -> dict[str, Any]:
    """What Muse knows of the board: the person's words, what it learned, dimensions on offer."""
    board = boards_repo.get(session, board_id)
    assert board is not None
    return {
        "your_words": board.context or "",
        "learned": [str(x) for x in (board.learned_json or [])],
        "offers": [asdict(o) for o in dimension_offers(session, board_id)],
    }
