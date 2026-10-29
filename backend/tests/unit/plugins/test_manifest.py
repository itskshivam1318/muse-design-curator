import json
from pathlib import Path
from typing import Any

import pytest

from app.plugins import manifest as mf
from app.plugins.manifest import ManifestError, load_manifest, to_tool

BUILTIN = Path(mf.__file__).parent / "builtin"


def base(**over: Any) -> dict[str, Any]:
    return {
        "id": "demo", "name": "Demo", "description": "Does a demo.", "mark": "DM",
        "tint": "#fff", "ink": "#000", "runner": "python", "runs_on": "Python",
        "inputs": {"kinds": ["image"]}, "outputs": ["notes"], "entry": "main.py", **over,
    }  # fmt: skip


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    (tmp_path / "plugin.json").write_text(json.dumps(data))
    (tmp_path / "main.py").write_text("def run(inputs, params, ctx): return {}\n")
    (tmp_path / "prompt.md").write_text("Prompt.\n")
    return tmp_path


def test_manifest_python_requires_entry(tmp_path: Path) -> None:
    d = base()
    del d["entry"]
    with pytest.raises(ManifestError, match="entry"):
        load_manifest(write(tmp_path, d), builtin=False)


def test_manifest_llm_requires_prompt_and_schema(tmp_path: Path) -> None:
    d = base(runner="llm", prompt="prompt.md")
    del d["entry"]
    with pytest.raises(ManifestError, match="output_schema"):
        load_manifest(write(tmp_path, d), builtin=False)
    d = base(runner="llm", output_schema={"type": "object"})
    del d["entry"]
    with pytest.raises(ManifestError, match="prompt"):
        load_manifest(write(tmp_path, d), builtin=False)
    d = base(runner="llm", prompt="prompt.md", output_schema={"type": "object"})
    del d["entry"]
    assert load_manifest(write(tmp_path, d), builtin=False).runner == "llm"


def test_user_manifest_model_runner_rejected(tmp_path: Path) -> None:
    d = base(runner="model", model="image.edit")
    del d["entry"]
    folder = write(tmp_path, d)
    with pytest.raises(ManifestError, match="built-in"):
        load_manifest(folder, builtin=False)
    assert load_manifest(folder, builtin=True).model == "image.edit"


def test_model_runner_requires_model(tmp_path: Path) -> None:
    d = base(runner="model")
    del d["entry"]
    with pytest.raises(ManifestError, match="model"):
        load_manifest(write(tmp_path, d), builtin=True)


@pytest.mark.parametrize("bad", ["A", "x", "1abc", "has space", "a" * 33, "../evil"])
def test_bad_id_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ManifestError):
        load_manifest(write(tmp_path, base(id=bad)), builtin=False)


def test_entry_must_stay_inside_folder_and_exist(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(write(tmp_path, base(entry="../x.py")), builtin=False)
    with pytest.raises(ManifestError, match="missing"):
        load_manifest(write(tmp_path, base(entry="nope.py")), builtin=False)


def test_unknown_params_schema_keys_are_kept(tmp_path: Path) -> None:
    params = {"type": "object", "properties": {"a": {"type": "string", "x-show-if": {"b": 1}}}}
    m = load_manifest(write(tmp_path, base(params=params, output_map={"a": "b"})), builtin=False)
    assert m.params == params
    assert m.output_map == {"a": "b"}


def test_invalid_json_reports_reason(tmp_path: Path) -> None:
    (tmp_path / "plugin.json").write_text("{nope")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path, builtin=False)
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "absent", builtin=False)


def test_every_builtin_loads_and_converts_to_tool() -> None:
    folders = sorted(p for p in BUILTIN.iterdir() if p.is_dir())
    assert len(folders) == 14
    for folder in folders:
        m = load_manifest(folder, builtin=True)
        assert m.id == folder.name
        tool = to_tool(m)
        assert tool["name"] == m.id
        assert "item_ids" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["required"] == ["item_ids"]
        assert tool["input_schema"]["properties"]["item_ids"]["minItems"] == m.inputs.min


def test_image_builtin_spec() -> None:
    m = load_manifest(BUILTIN / "image", builtin=True)
    assert (m.runner, m.model, m.secondary) == ("model", "image.edit", "Prompt")
    assert m.params["properties"]["count"]["maximum"] == 4
