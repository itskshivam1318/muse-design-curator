import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.kinds import AttributeSpec, check_snake

LENS_DIR = Path(__file__).resolve().parents[1] / "lenses"
_FORBIDDEN_PROMPT = re.compile(r"(\band\b|,|\bor\b|\bnot\b)", re.IGNORECASE)


class PartSpec(BaseModel):
    id: str
    sam_prompt: str
    grounding: Literal["sam", "whole_image"] = "sam"

    @field_validator("id")
    @classmethod
    def _id_snake(cls, v: str) -> str:
        return check_snake(v)

    @field_validator("sam_prompt")
    @classmethod
    def _prompt_ok(cls, v: str) -> str:
        if not 1 <= len(v.split()) <= 3:
            raise ValueError("sam_prompt must be 1-3 words")
        if _FORBIDDEN_PROMPT.search(v):
            raise ValueError("sam_prompt must name a single thing (no and/or/not/commas)")
        return v


class LensSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*@\d+$")
    domain: str
    label: str
    origin: Literal["curated", "proposed", "edited"]
    parts: list[PartSpec] = Field(max_length=8)
    attributes: list[AttributeSpec] = Field(max_length=20)
    notes: list[str] = []

    @field_validator("domain")
    @classmethod
    def _domain_snake(cls, v: str) -> str:
        return check_snake(v)

    @model_validator(mode="after")
    def _consistent(self) -> "LensSpec":
        keys = [a.key for a in self.attributes]
        if len(set(keys)) != len(keys):
            raise ValueError("attribute keys must be unique")
        part_ids = [p.id for p in self.parts]
        if len(set(part_ids)) != len(part_ids):
            raise ValueError("part ids must be unique")
        for a in self.attributes:
            if a.part is not None and a.part not in part_ids:
                raise ValueError(f"attribute {a.key} references undeclared part {a.part}")
        return self


def validate_lens(spec: LensSpec, shape_enabled: bool) -> LensSpec:
    if not shape_enabled and any(a.kind == "shape" for a in spec.attributes):
        raise ValueError("shape attributes are disabled")
    return spec


def load_curated_lens(domain: str, shape_enabled: bool) -> LensSpec | None:
    try:
        check_snake(domain)
    except ValueError:
        return None
    path = LENS_DIR / f"{domain}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not shape_enabled:
        data["attributes"] = [a for a in data["attributes"] if a.get("kind") != "shape"]
    return validate_lens(LensSpec.model_validate(data), shape_enabled)
