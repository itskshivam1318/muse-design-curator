import json
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.plugins import registry
from app.plugins.registry import discover, load_packs, status


def user_plugin(root: Path, pid: str, **over: Any) -> None:
    d = root / pid
    d.mkdir(parents=True)
    (d / "main.py").write_text("def run(inputs, params, ctx): return {}\n")
    data = {
        "id": pid, "name": pid, "description": "x", "mark": "U", "tint": "#fff", "ink": "#000",
        "runner": "python", "runs_on": "Python", "inputs": {"kinds": ["image"]},
        "outputs": ["notes"], "entry": "main.py", **over,
    }  # fmt: skip
    (d / "plugin.json").write_text(json.dumps(data))


def settings(tmp_path: Path, **over: Any) -> Settings:
    return Settings(PLUGINS_DIR=str(tmp_path / "user"), **over)


def test_discover_loads_builtins_and_user(tmp_path: Path) -> None:
    user_plugin(tmp_path / "user", "mine")
    found, skipped = discover(settings(tmp_path))
    assert {"image", "palette", "critique", "mine"} <= set(found)
    assert found["image"].builtin and not found["mine"].builtin
    assert skipped == []


def test_discover_skips_invalid_with_reason(tmp_path: Path) -> None:
    (tmp_path / "user" / "broken").mkdir(parents=True)
    (tmp_path / "user" / "broken" / "plugin.json").write_text("{not json")
    (tmp_path / "user" / "nofile").mkdir()
    found, skipped = discover(settings(tmp_path))
    assert "image" in found
    assert {s["folder"] for s in skipped} == {"broken", "nofile"}
    assert all(s["reason"] for s in skipped)


def test_user_cannot_shadow_builtin(tmp_path: Path) -> None:
    user_plugin(tmp_path / "user", "image")
    found, skipped = discover(settings(tmp_path))
    assert found["image"].builtin
    assert skipped == [{"folder": "image", "reason": "shadows a built-in"}]


def test_demo_mode_skips_user_plugins(tmp_path: Path) -> None:
    user_plugin(tmp_path / "user", "mine")
    found, skipped = discover(settings(tmp_path, DEMO_MODE=True))
    assert "mine" not in found and "image" in found
    assert skipped == []


def test_status_not_connected_when_requires_unset(tmp_path: Path) -> None:
    found, _ = discover(settings(tmp_path))
    assert status(found["image"], settings(tmp_path)) == "available"
    assert status(found["palette"], settings(tmp_path)) == "available"
    assert status(found["video"], settings(tmp_path)) == "not_connected"
    assert status(found["mesh"], settings(tmp_path, MESH_MODEL="m")) == "not_connected"
    assert status(found["code"], settings(tmp_path)) == "not_connected"
    assert status(found["code"], settings(tmp_path, CODE_SANDBOX="docker")) == "available"
    assert status(found["bom"], settings(tmp_path)) == "not_connected"


def test_packs_drop_unknown_and_append_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packs_file = tmp_path / "packs.json"
    packs_file.write_text(
        json.dumps([{"id": "p", "name": "P", "about": "a", "plugin_ids": ["image", "ghost"]}])
    )
    monkeypatch.setattr(registry, "PACKS_FILE", packs_file)
    monkeypatch.setattr(registry, "_cache", None)
    packs = load_packs()
    assert packs[0]["plugin_ids"] == ["image"]
    last = packs[-1]
    assert last["id"] == "all" and last["name"] == "All plugins"
    assert last["plugin_ids"] == sorted(registry.get_registry())


def test_shipped_packs_reference_only_builtins() -> None:
    raw = json.loads(registry.PACKS_FILE.read_text())
    ids = set(registry.get_registry())
    assert [p["id"] for p in raw] == ["product", "fashion", "interior", "auto", "lab"]
    for p in raw:
        assert set(p["plugin_ids"]) <= ids, p["id"]


def test_builtin_statuses(tmp_path: Path) -> None:
    found, _ = discover(settings(tmp_path))
    s = settings(tmp_path)
    for pid in ("image", "palette", "critique"):
        assert status(found[pid], s) == "available", pid
    for pid in ("video", "mesh", "code", "fit", "formula"):
        assert status(found[pid], s) == "not_connected", pid


def test_false_bool_setting_counts_as_unset(tmp_path: Path) -> None:
    found, _ = discover(settings(tmp_path))
    p = found["image"]
    p.manifest = p.manifest.model_copy(update={"requires": ["EXPLORE_ENABLED"]})
    assert status(p, settings(tmp_path, EXPLORE_ENABLED=True)) == "available"
    assert status(p, settings(tmp_path, EXPLORE_ENABLED=False)) == "not_connected"
