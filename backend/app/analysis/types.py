from typing import Any, Literal

from pydantic import BaseModel, model_validator

from app.providers.reasoning import strict_schema

AttrKind = Literal["enum", "ordinal", "number", "boolean", "color", "text", "shape"]
RegionKind = Literal["mask", "box", "text_range"]
DimType = Literal["physical", "abstract"]
ContentType = Literal["image", "ui", "text"]

MAX_PARTS = 8
MAX_DIMENSIONS = 20


class Region(BaseModel):
    kind: RegionKind
    box: list[float] | None = None
    range: list[int] | None = None
    mask_url: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Region":
        if self.box is not None and (len(self.box) != 4 or any(not 0 <= v <= 1 for v in self.box)):
            raise ValueError("box must be 4 floats in 0..1")
        if self.range is not None and (len(self.range) != 2 or self.range[0] >= self.range[1]):
            raise ValueError("range must be [start, end] with start < end")
        return self


class PartOut(BaseModel):
    key: str
    label: str
    region_kind: RegionKind
    region: list[float] | list[int] | None = None


class DimensionOut(BaseModel):
    key: str
    label: str
    type: DimType
    part: str | None = None
    prompt: str | None = None
    kind: AttrKind
    value: Any = None
    confidence: float
    vocabulary: list[str] = []
    scale: list[str] = []
    min: float | None = None
    max: float | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _type_rules(self) -> "DimensionOut":
        if (self.type == "physical") != (self.part is not None):
            raise ValueError("a dimension is physical if and only if it has a part")
        if self.type == "abstract" and not self.prompt:
            raise ValueError("an abstract dimension requires a prompt")
        # Imported here: spec.py imports this module.
        from app.analysis.spec import spec_from_dimension

        try:
            spec_from_dimension(self)
        except ValueError as e:  # includes pydantic ValidationError
            raise ValueError(f"dimension {self.key} cannot form a {self.kind} spec: {e}") from e
        return self


class Analysis(BaseModel):
    content_type: ContentType
    summary: str
    parts: list[PartOut]
    dimensions: list[DimensionOut]

    @model_validator(mode="after")
    def _limits(self) -> "Analysis":
        if len(self.parts) > MAX_PARTS:
            raise ValueError(f"at most {MAX_PARTS} parts")
        if len(self.dimensions) > MAX_DIMENSIONS:
            raise ValueError(f"at most {MAX_DIMENSIONS} dimensions")
        return self


def _build_schema() -> dict[str, Any]:
    schema = Analysis.model_json_schema()
    schema["title"] = "item_analysis"
    schema["properties"]["parts"]["maxItems"] = MAX_PARTS
    schema["properties"]["dimensions"]["maxItems"] = MAX_DIMENSIONS
    return strict_schema(schema)


ANALYSIS_SCHEMA: dict[str, Any] = _build_schema()
