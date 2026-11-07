"""Plugin discovery: built-ins shipped in the app plus user folders in PLUGINS_DIR."""

import importlib.util
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from app.config import Settings, get_settings, resolve_repo_path
from app.plugins.manifest import Manifest, ManifestError, load_manifest

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "builtin"
PACKS_FILE = Path(__file__).parent / "packs.json"
NOT_CONNECTED_MODELS: set[str] = set()


def load_builtin_module(plugin_id: str, module: str) -> ModuleType:
    """Import `<plugin_id>/<module>.py` from the built-in plugins by file path (host side).
    Loaded once; the module must not import `app`, since the plugin shim loads it in isolation."""
    name = f"muse_builtin_{plugin_id}_{module}"
    if name in sys.modules:
        return sys.modules[name]
    path = BUILTIN_DIR / plugin_id / f"{module}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


@dataclass
class Plugin:
    manifest: Manifest
    folder: Path
    builtin: bool


Status = Literal["available", "not_connected"]


def status(p: Plugin, settings: Settings | None = None) -> Status:
    settings = settings or get_settings()
    if p.manifest.runner == "model" and p.manifest.model in NOT_CONNECTED_MODELS:
        return "not_connected"
    for name in p.manifest.requires:
        # a name that is not a setting (the placeholder marker) is always unset
        if getattr(settings, name, None) in (None, "", False):
            return "not_connected"
    return "available"


def _folders(root: Path) -> list[Path]:
    try:
        return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []


def discover(settings: Settings) -> tuple[dict[str, Plugin], list[dict[str, str]]]:
    found: dict[str, Plugin] = {}
    skipped: list[dict[str, str]] = []
    for folder in _folders(BUILTIN_DIR):
        try:
            found[folder.name] = Plugin(load_manifest(folder, builtin=True), folder, True)
        except ManifestError as e:  # a broken built-in is a packaging bug; keep the rest running
            log.error("built-in plugin %s is invalid: %s", folder.name, e.reason)
            skipped.append({"folder": folder.name, "reason": e.reason})
    if settings.DEMO_MODE:
        return found, skipped
    for folder in _folders(resolve_repo_path(settings.PLUGINS_DIR)):
        try:
            m = load_manifest(folder, builtin=False)
        except ManifestError as e:
            skipped.append({"folder": folder.name, "reason": e.reason})
            continue
        if m.id in found:
            reason = "shadows a built-in" if found[m.id].builtin else "duplicate id"
            skipped.append({"folder": folder.name, "reason": reason})
            continue
        found[m.id] = Plugin(m, folder, False)
    return found, skipped


_cache: tuple[dict[str, Plugin], list[dict[str, str]]] | None = None


def _state() -> tuple[dict[str, Plugin], list[dict[str, str]]]:
    global _cache
    if _cache is None:
        _cache = discover(get_settings())
    return _cache


def get_registry() -> dict[str, Plugin]:
    return _state()[0]


def reload() -> dict[str, Any]:
    global _cache
    _cache = discover(get_settings())
    plugins, skipped = _cache
    return {"loaded": sorted(plugins), "skipped": skipped}


def load_packs() -> list[dict[str, Any]]:
    ids = set(get_registry())
    packs = [
        {
            "id": p["id"], "name": p["name"], "about": p["about"],
            "plugin_ids": [i for i in p["plugin_ids"] if i in ids],
        }
        for p in json.loads(PACKS_FILE.read_text(encoding="utf-8"))
    ]  # fmt: skip
    packs.append(
        {"id": "all", "name": "All plugins", "about": "Everything available.",
         "plugin_ids": sorted(ids)}
    )  # fmt: skip
    return packs
