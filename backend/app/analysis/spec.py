from typing import Any

from pydantic import TypeAdapter

from app.analysis.types import DimensionOut, DimType
from app.db.models import ItemAttribute
from app.domain.kinds import (
    AttributeSpec,
    BooleanSpec,
    ColorSpec,
    EnumSpec,
    NumberSpec,
    OrdinalSpec,
    ShapeSpec,
    TextSpec,
)
from app.domain.lens import LensSpec

_SPEC_ADAPTER: TypeAdapter[AttributeSpec] = TypeAdapter(AttributeSpec)


def spec_for(row: ItemAttribute, lens: LensSpec | None = None) -> AttributeSpec:
    """The spec governing an item attribute: its stored spec, else the lens's, else free text."""
    if row.spec_json:
        return _SPEC_ADAPTER.validate_python(row.spec_json)
    if lens is not None:
        for attr in lens.attributes:
            if attr.key == row.key:
                return attr
    return TextSpec(key=row.key, label=row.label, category=row.category)


def spec_for_key(key: str, lens: LensSpec | None = None) -> AttributeSpec:
    """The spec of a key the item has no row for (a legacy exploration): the lens's, else free
    text read as an abstract dimension."""
    if lens is not None:
        for attr in lens.attributes:
            if attr.key == key:
                return attr
    return TextSpec(key=key, label=key.replace("_", " ").capitalize(), category="abstract")


def spec_from_dimension(d: DimensionOut) -> AttributeSpec:
    common: dict[str, Any] = {"key": d.key, "label": d.label, "category": d.type, "part": d.part}
    match d.kind:
        case "enum":
            return EnumSpec(**common, vocabulary=d.vocabulary or None, open_vocabulary=True)
        case "ordinal":
            return OrdinalSpec(**common, scale=d.scale)
        case "number":
            if d.min is None or d.max is None:
                raise ValueError(f"number dimension {d.key} needs min and max")
            return NumberSpec(
                **common,
                unit=d.unit or "",
                min=d.min,
                max=d.max,
                tolerance=(d.max - d.min) / 20,
            )
        case "boolean":
            return BooleanSpec(**common)
        case "color":
            return ColorSpec(**common)
        case "shape":
            return ShapeSpec(**common)
        case _:
            return TextSpec(**common)


def dimension_type(row: ItemAttribute) -> DimType:
    """A row with a part is physical, whatever its stored type; otherwise the stored type."""
    return "physical" if row.part or row.dim_type == "physical" else "abstract"
