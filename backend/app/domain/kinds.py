import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def check_snake(value: str) -> str:
    if not SNAKE_RE.match(value):
        raise ValueError(f"{value!r} is not snake_case")
    return value


class _Base(BaseModel):
    key: str
    label: str
    category: str
    part: str | None = None

    @field_validator("key")
    @classmethod
    def _key_snake(cls, v: str) -> str:
        return check_snake(v)


class EnumSpec(_Base):
    kind: Literal["enum"] = "enum"
    vocabulary: list[str] | None = None
    open_vocabulary: bool = False

    @model_validator(mode="after")
    def _vocab_required(self) -> "EnumSpec":
        if not self.open_vocabulary and not self.vocabulary:
            raise ValueError("enum needs a vocabulary unless open_vocabulary is set")
        return self


class OrdinalSpec(_Base):
    kind: Literal["ordinal"] = "ordinal"
    scale: list[str] = Field(min_length=3, max_length=7)

    @field_validator("scale")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("scale steps must be unique")
        return v


class NumberSpec(_Base):
    kind: Literal["number"] = "number"
    unit: str
    min: float
    max: float
    tolerance: float = Field(gt=0)
    measure: Literal["model", "mask_ratio", "palette_count"] = "model"

    @model_validator(mode="after")
    def _range(self) -> "NumberSpec":
        if self.min >= self.max:
            raise ValueError("min must be below max")
        return self


class BooleanSpec(_Base):
    kind: Literal["boolean"] = "boolean"


class ColorSpec(_Base):
    kind: Literal["color"] = "color"


class TextSpec(_Base):
    kind: Literal["text"] = "text"
    hint: str | None = None


class ShapeSpec(_Base):
    kind: Literal["shape"] = "shape"
    experimental: Literal[True] = True

    @model_validator(mode="after")
    def _part_required(self) -> "ShapeSpec":
        if self.part is None:
            raise ValueError("shape attributes require a part")
        return self


AttributeSpec = Annotated[
    EnumSpec | OrdinalSpec | NumberSpec | BooleanSpec | ColorSpec | TextSpec | ShapeSpec,
    Field(discriminator="kind"),
]
