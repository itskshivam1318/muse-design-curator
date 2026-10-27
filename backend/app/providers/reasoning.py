"""Reasoning providers: read images into schema-constrained JSON."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Protocol

import httpx2
import openai

from app.explore.schema import CHECK_SCHEMA, OPTIONS_SCHEMA
from app.providers.meta_client import check_model_id, data_url
from app.providers.reliability import ModelError, call_model

MAX_EXTRACT_IMAGES = 6
MAX_PROPOSE_IMAGES = 20
MAX_VERIFY_IMAGES = 50
MAX_EXPLORE_IMAGES = 4
BASETEN_URL = "https://inference.baseten.co/v1"
SCHEMA_NAME = "design_language"


class ReasoningProvider(Protocol):
    id: str
    model: str
    is_mock: bool

    def extract(
        self, images: list[bytes], schema: dict[str, Any], prompt: str
    ) -> dict[str, Any]: ...

    def propose_lens(
        self, images: list[bytes], context: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...

    def verify(
        self, images: list[bytes], schema: dict[str, Any], prompt: str
    ) -> dict[str, Any]: ...

    def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]: ...

    def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]: ...


def _limit(images: list[bytes], maximum: int) -> None:
    if len(images) > maximum:
        raise ModelError("TOO_MANY_IMAGES", message=f"{len(images)} images given, max {maximum}")


def parse_json_text(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text, tolerating code fences and surrounding prose."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    candidates = [s]
    if "{" in s and "}" in s:
        candidates.append(s[s.index("{") : s.rindex("}") + 1])
    for c in candidates:
        try:
            out = json.loads(c)
        except ValueError:
            continue
        if isinstance(out, dict):
            return out
    raise ModelError("MODEL_INVALID_RESPONSE", message="model output is not a JSON object")


def _responses_input(prompt: str, images: list[bytes]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": data_url(b)} for b in images]
    return [{"role": "user", "content": content}]


class MuseSparkProvider:
    id = "muse_spark"
    is_mock = False

    def __init__(
        self, client: openai.OpenAI, model: str, *, max_retries: int = 2, timeout: float = 60
    ) -> None:
        self.client = client
        self.model = check_model_id(model)
        self.max_retries = max_retries
        self.timeout = timeout

    def _fmt(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {"format": {"type": "json_schema", "name": SCHEMA_NAME, "schema": schema,
                           "strict": True}}  # fmt: skip

    def _kwargs(
        self, prompt: str, images: list[bytes], schema: dict[str, Any], effort: str
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": _responses_input(prompt, images),
            "text": self._fmt(schema),
            "reasoning": {"effort": effort},
            "store": False,
        }

    def _run(
        self, prompt: str, images: list[bytes], schema: dict[str, Any], effort: str
    ) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            resp = self.client.responses.create(**self._kwargs(prompt, images, schema, effort))
            return parse_json_text(resp.output_text)

        return call_model(go, timeout=self.timeout, max_retries=self.max_retries)

    def extract(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXTRACT_IMAGES)
        return self._run(prompt, images, schema, "low")

    def propose_lens(
        self, images: list[bytes], context: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        _limit(images, MAX_PROPOSE_IMAGES)
        return self._run(context, images, schema, "medium")

    def verify(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_VERIFY_IMAGES)

        def go() -> dict[str, Any]:
            stream = self.client.responses.create(
                **self._kwargs(prompt, images, schema, "medium"), stream=True
            )
            parts: list[str] = []
            for ev in stream:
                if ev.type == "response.output_text.delta":
                    parts.append(ev.delta)
                elif ev.type in ("response.failed", "error"):
                    raise ModelError("MODEL_UNAVAILABLE", message="stream reported a failure")
            return parse_json_text("".join(parts))

        return call_model(go, timeout=self.timeout, max_retries=self.max_retries)

    def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXPLORE_IMAGES)
        return self._run(prompt, images, OPTIONS_SCHEMA, "low")

    def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXPLORE_IMAGES)
        return self._run(prompt, images, CHECK_SCHEMA, "low")


class MuseSparkOpenProvider:
    """Open-weights Muse Spark on Baseten via chat completions; JSON is parsed from text."""

    id = "muse_spark_open"
    is_mock = False

    def __init__(
        self,
        base_url: str = BASETEN_URL,
        api_key: str = "",
        model: str = "meta-models/muse-spark-open",
        *,
        max_retries: int = 2,
        timeout: float = 60,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self.model = check_model_id(model)
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key or "unset",
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )
        self.max_retries = max_retries
        self.timeout = timeout

    def _run(self, prompt: str, images: list[bytes], schema: dict[str, Any]) -> dict[str, Any]:
        text = (
            f"{prompt}\n\nReply with a single JSON object only, matching this JSON schema:\n"
            f"{json.dumps(schema)}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content += [{"type": "image_url", "image_url": {"url": data_url(b)}} for b in images]

        def once() -> str:
            messages: list[Any] = [{"role": "user", "content": content}]
            r = self.client.chat.completions.create(model=self.model, messages=messages)
            return r.choices[0].message.content or ""

        last: ModelError | None = None
        for _ in range(2):  # one retry on unparseable output
            out = call_model(once, timeout=self.timeout, max_retries=self.max_retries)
            try:
                return parse_json_text(out)
            except ModelError as err:
                last = err
        assert last is not None
        raise last

    def extract(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXTRACT_IMAGES)
        return self._run(prompt, images, schema)

    def propose_lens(
        self, images: list[bytes], context: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        _limit(images, MAX_PROPOSE_IMAGES)
        return self._run(context, images, schema)

    def verify(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_VERIFY_IMAGES)
        return self._run(prompt, images, schema)

    def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXPLORE_IMAGES)
        return self._run(prompt, images, OPTIONS_SCHEMA)

    def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXPLORE_IMAGES)
        return self._run(prompt, images, CHECK_SCHEMA)


GENERIC_LENS: dict[str, Any] = {
    "label": "Custom",
    "notes": [],
    "parts": [
        {"id": "object", "sam_prompt": "object", "grounding": "sam"},
        {"id": "background", "sam_prompt": "background", "grounding": "whole_image"},
    ],
    "attributes": [
        {"key": "primary_color", "label": "Primary color", "category": "color",
         "kind": "color", "part": "object"},
        {"key": "material", "label": "Material", "category": "material", "kind": "enum",
         "part": "object", "open_vocabulary": True},
        {"key": "form", "label": "Form", "category": "form", "kind": "enum",
         "part": "object", "open_vocabulary": True},
        {"key": "finish", "label": "Finish", "category": "surface", "kind": "ordinal",
         "part": "object", "scale": ["matte", "satin", "gloss"]},
        {"key": "density", "label": "Density", "category": "composition", "kind": "ordinal",
         "part": "background", "scale": ["sparse", "balanced", "dense"]},
        {"key": "has_pattern", "label": "Has pattern", "category": "surface",
         "kind": "boolean", "part": "object"},
        {"key": "style", "label": "Style", "category": "style", "kind": "text"},
    ],
}  # fmt: skip


class MockReasoningProvider:
    """Deterministic output derived from SHA-256 of inputs and schema.

    `truth` maps a property name to a ground-truth value; when the property is an object that
    has a `value` field (and `confidence`), the value is filled in with confidence 0.9.
    Without `truth`, `propose_lens` returns a fixed, valid generic lens.
    """

    id = "mock"
    model = "mock-reasoning"
    is_mock = True

    def __init__(self, truth: dict[str, Any] | None = None) -> None:
        self.truth = truth or {}

    def extract(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXTRACT_IMAGES)
        return self._make(images, schema, prompt)

    def propose_lens(
        self, images: list[bytes], context: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        _limit(images, MAX_PROPOSE_IMAGES)
        if not self.truth:
            return copy.deepcopy(GENERIC_LENS)
        return self._make(images, schema, context)

    def verify(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_VERIFY_IMAGES)
        return self._make(images, schema, prompt)

    def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXPLORE_IMAGES)
        distances = ("near", "bold", "wild")
        tag = hashlib.sha256(prompt.encode()).hexdigest()[:4]  # new names for each new prompt
        return {
            "options": [
                {
                    "name": f"Option {c} {tag}",
                    "description": f"A mock design move {c}.",
                    "distance": distances[i % 3],
                    "value": f"option_{c.lower()}_{tag}",
                    "keeps": [],
                    "edit_prompt": f"Change only the target attribute to option {c}.",
                }
                for i, c in enumerate("ABCDEFGH")
            ]
        }

    def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        _limit(images, MAX_EXPLORE_IMAGES)
        if self.truth:
            return {"answer": "yes", "confidence": 0.9, "box": None, "note": ""}
        n = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
        return {"answer": ("yes", "no", "unclear")[n % 3], "confidence": round(0.5 + (n % 40) / 100, 2),
                "box": None, "note": ""}  # fmt: skip

    def _make(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        h = hashlib.sha256()
        for img in images:
            h.update(hashlib.sha256(img).digest())
        h.update(prompt.encode())
        h.update(json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str).encode())
        seed = h.hexdigest()
        out = self._gen(schema, schema, seed, "$", None)
        return out if isinstance(out, dict) else {"value": out}

    def _gen(self, node: dict[str, Any], root: dict[str, Any], seed: str, path: str,
             key: str | None) -> Any:  # fmt: skip
        if "$ref" in node:
            target: Any = root
            for part in node["$ref"].lstrip("#/").split("/"):
                target = target[part]
            return self._gen(target, root, seed, path, key)
        for alt in ("anyOf", "oneOf"):
            if alt in node:
                opts = [o for o in node[alt] if o.get("type") != "null"] or node[alt]
                return self._gen(opts[0], root, seed, path, key)
        n = int(hashlib.sha256(f"{seed}|{path}".encode()).hexdigest()[:12], 16)
        if "const" in node:
            return node["const"]
        if key == "confidence":
            return round(0.45 + (n % 2001) / 10000, 4)
        if key is not None and key in self.truth and node.get("type") != "object":
            return self.truth[key]
        if "enum" in node:
            return node["enum"][n % len(node["enum"])]
        t = node.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), "null")
        if t == "object" or "properties" in node:
            props = node.get("properties", {})
            obj = {k: self._gen(v, root, seed, f"{path}.{k}", k) for k, v in props.items()}
            if key is not None and key in self.truth and "value" in props:
                obj["value"] = self.truth[key]
                if "confidence" in props:
                    obj["confidence"] = 0.9
            return obj
        if t == "array":
            lo = int(node.get("minItems", 1))
            return [self._gen(node.get("items", {}), root, seed, f"{path}[{i}]", None)
                    for i in range(max(lo, 1))]  # fmt: skip
        if t == "boolean":
            return bool(n % 2)
        if t in ("integer", "number"):
            lo = node.get("minimum", 0)
            hi = node.get("maximum", lo + 10)
            if t == "integer":
                return int(lo) + n % (int(hi) - int(lo) + 1)
            return round(lo + (n % 10001) / 10000 * (hi - lo), 4)
        if t == "null":
            return None
        return f"mock-{n % 10000:04d}"
