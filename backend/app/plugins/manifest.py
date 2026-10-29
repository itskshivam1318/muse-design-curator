"""Plugin manifests: one `plugin.json` per plugin folder, convertible to an agent tool."""

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Kind = Literal["image", "video", "note", "link"]
Output = Literal["images", "notes", "attributes", "text", "table"]
ModelName = Literal["image.edit", "image.generate", "video.generate", "mesh.from_image"]


class ManifestError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class InputSpec(BaseModel):
    kinds: list[Kind]
    min: int = Field(default=1, ge=0)
    max: int = Field(default=12, ge=1)


def _empty_params() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


class Manifest(BaseModel):
    # Unknown top-level keys are ignored; params is stored as-is, so unknown schema keys survive.
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    name: str = Field(min_length=1)
    description: str
    mark: str = Field(min_length=1, max_length=4)
    tint: str
    ink: str
    runner: Literal["python", "llm", "model"]
    runs_on: str
    inputs: InputSpec
    params: dict[str, Any] = Field(default_factory=_empty_params)
    outputs: list[Output]
    requires: list[str] = Field(default_factory=list)
    entry: str | None = None
    prompt: str | None = None
    output_schema: dict[str, Any] | None = None
    output_map: dict[str, str] | None = None
    model: ModelName | None = None
    secondary: str | None = None

    @model_validator(mode="after")
    def _runner_fields(self) -> Self:
        if self.runner == "python" and not self.entry:
            raise ValueError("python runner needs entry")
        if self.runner == "llm":
            if not self.prompt:
                raise ValueError("llm runner needs prompt")
            if self.output_schema is None:
                raise ValueError("llm runner needs output_schema")
        if self.runner == "model" and not self.model:
            raise ValueError("model runner needs model")
        if self.inputs.min > self.inputs.max:
            raise ValueError("inputs.min is above inputs.max")
        return self


def _check_file(folder: Path, rel: str, field: str) -> None:
    root = folder.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ManifestError(f"{field} {rel!r} leaves the plugin folder")
    if not target.is_file():
        raise ManifestError(f"{field} file {rel!r} is missing")


def load_manifest(folder: Path, *, builtin: bool) -> Manifest:
    path = folder / "plugin.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError("plugin.json is missing") from None
    except (OSError, ValueError) as e:
        raise ManifestError(f"plugin.json is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ManifestError("plugin.json must be an object")
    try:
        m = Manifest.model_validate(raw)
    except ValidationError as e:
        raise ManifestError(
            "; ".join(
                f"{'.'.join(map(str, x['loc'])) or 'manifest'}: {x['msg']}" for x in e.errors()
            )
        ) from None
    if m.runner == "model" and not builtin:
        raise ManifestError("model runner is only available to built-in plugins")
    if m.entry:
        _check_file(folder, m.entry, "entry")
    if m.runner == "llm" and m.prompt:
        _check_file(folder, m.prompt, "prompt")
    return m


def to_tool(m: Manifest) -> dict[str, Any]:
    """The manifest as an agent tool definition."""
    return {
        "name": m.id,
        "description": m.description,
        "input_schema": {
            "type": "object",
            "properties": {
                "item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": m.inputs.min,
                    "maxItems": m.inputs.max,
                },
                "params": m.params,
            },
            "required": ["item_ids"],
        },
    }
