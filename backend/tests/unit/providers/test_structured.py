import json
from types import SimpleNamespace
from typing import Any

from app.plugins.manifest import load_manifest
from app.plugins.registry import BUILTIN_DIR
from app.providers.reasoning import MuseSparkProvider, strict_schema


class FakeResponses:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return SimpleNamespace(output_text=json.dumps(self.reply))


MAPS = ("properties", "$defs", "definitions")


def closed_everywhere(node: Any) -> bool:
    if isinstance(node, dict):
        if node.get("type") == "object" or isinstance(node.get("properties"), dict):
            props = node.get("properties", {})
            if node.get("additionalProperties") is not False:
                return False
            if sorted(node.get("required", [])) != sorted(props):
                return False
        return all(
            all(map(closed_everywhere, v.values())) if k in MAPS and isinstance(v, dict)
            else closed_everywhere(v)
            for k, v in node.items()
        )  # fmt: skip
    if isinstance(node, list):
        return all(closed_everywhere(v) for v in node)
    return True


def test_structured_request_is_strict_with_closed_schema() -> None:
    schema = load_manifest(BUILTIN_DIR / "critique", builtin=True).output_schema
    assert schema is not None
    original = json.dumps(schema, sort_keys=True)
    responses = FakeResponses({"points": [], "summary": "ok"})
    client: Any = SimpleNamespace(responses=responses)
    out = MuseSparkProvider(client, "muse-spark-1.3", max_retries=0, timeout=5).structured(
        [b"img"], schema, "critique this"
    )
    assert out == {"points": [], "summary": "ok"}
    fmt = responses.calls[0]["text"]["format"]
    assert fmt["strict"] is True
    assert fmt["name"] == "plugin_output"
    assert closed_everywhere(fmt["schema"])
    assert fmt["schema"]["properties"]["points"]["items"]["required"] == ["verdict", "text"]
    assert json.dumps(schema, sort_keys=True) == original  # the manifest's schema is not mutated


def test_strict_schema_closes_nested_and_optional() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "array", "items": {"type": "object", "properties": {"x": {}}}},
            "c": {"anyOf": [{"type": "object", "properties": {"y": {}}}, {"type": "null"}]},
            "properties": {"type": "string"},  # a property that happens to be named "properties"
        },
        "required": ["a"],
        "$defs": {"d": {"type": "object", "properties": {"z": {}}}},
    }
    s = strict_schema(schema)
    assert closed_everywhere(s)
    assert s["required"] == ["a", "b", "c", "properties"]
    assert s["properties"]["properties"] == {"type": "string"}
    assert s["$defs"]["d"]["additionalProperties"] is False
    assert "required" not in schema["properties"]["b"]["items"]  # copy, not in place
