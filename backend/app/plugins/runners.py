"""Plugin execution: validate inputs and params, dispatch by runner, validate the output.

The python runner is isolation from the app (separate process, stripped env, temp cwd), not a
security sandbox: plugins are local and trusted.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.plugins.manifest import Manifest
from app.plugins.registry import Plugin, status
from app.providers import get_image_provider, get_reasoning
from app.providers.reasoning import MAX_STRUCTURED_IMAGES
from app.providers.reliability import ModelError

SHIM = Path(__file__).parent / "shim.py"
SHIM_BAD_RESULT_EXIT = 3  # shim.py: run() returned something json.dumps cannot encode
MAX_STDOUT = 1024 * 1024
STDERR_TAIL = 4096
OUTPUT_KINDS = ("images", "notes", "attributes", "text", "table")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_IMAGE_RESULTS = 8  # image results per run, across all inputs
PART_PROMPT = "Change only the {part}: {prompt}. Keep everything else exactly the same."


@dataclass
class RunInput:
    id: str
    kind: str
    label: str
    attributes: dict[str, Any]
    note_text: str | None
    image: bytes | None


@dataclass
class BoardCtx:
    title: str
    context: str | None
    notes: list[str]


class PluginError(Exception):
    """code: PLUGIN_TIMEOUT | PLUGIN_CRASHED | PLUGIN_BAD_OUTPUT | PLUGIN_BAD_INPUT |
    PLUGIN_NOT_CONNECTED | PLUGIN_MODEL_FAILED; message in plain words."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _bad_input(msg: str) -> PluginError:
    return PluginError("PLUGIN_BAD_INPUT", msg)


def _bad_output(msg: str) -> PluginError:
    return PluginError("PLUGIN_BAD_OUTPUT", msg)


# ---- input and param validation ------------------------------------------------------------


def check_input_kinds(m: Manifest, kinds: list[str]) -> None:
    """Count and kinds of the inputs against the manifest (also checked before a run queues)."""
    n = len(kinds)
    if n < m.inputs.min:
        raise _bad_input(f"{m.name} needs at least {m.inputs.min} input(s), got {n}")
    if n > m.inputs.max:
        raise _bad_input(f"{m.name} takes at most {m.inputs.max} input(s), got {n}")
    for kind in kinds:
        if kind not in m.inputs.kinds:
            raise _bad_input(f"{m.name} does not take {kind} items")


def check_inputs(m: Manifest, inputs: list[RunInput]) -> None:
    check_input_kinds(m, [i.kind for i in inputs])


def _type_ok(t: str, v: Any) -> bool:
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    return True  # types the manifests do not use are not checked


def check_params(m: Manifest, params: dict[str, Any]) -> dict[str, Any]:
    """Required keys, simple types, enum and minimum/maximum; defaults filled. Unknown schema
    keys (x-show-if, ...) are ignored."""
    if not isinstance(params, dict):
        raise _bad_input("params must be an object")
    schema = m.params or {}
    props: dict[str, Any] = schema.get("properties") or {}
    out = dict(params)
    if schema.get("additionalProperties") is False:
        extra = sorted(set(out) - set(props))
        if extra:
            raise _bad_input(f"unknown param {extra[0]!r}")
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        if key not in out:
            if "default" in spec:
                out[key] = spec["default"]
            continue
        v = out[key]
        t = spec.get("type")
        if isinstance(t, str) and not _type_ok(t, v):
            raise _bad_input(f"param {key!r} must be a {t}")
        if "enum" in spec and v not in spec["enum"]:
            raise _bad_input(f"param {key!r} must be one of {', '.join(map(str, spec['enum']))}")
        if isinstance(v, int | float) and not isinstance(v, bool):
            if "minimum" in spec and v < spec["minimum"]:
                raise _bad_input(f"param {key!r} must be at least {spec['minimum']}")
            if "maximum" in spec and v > spec["maximum"]:
                raise _bad_input(f"param {key!r} must be at most {spec['maximum']}")
    for key in schema.get("required") or []:
        if key not in out:
            raise _bad_input(f"param {key!r} is required")
    return out


# ---- output validation ---------------------------------------------------------------------


def _scalar(v: Any) -> bool:
    return isinstance(v, str | int | float | bool)


def _list_of_dicts(out: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    v = out[kind]
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise _bad_output(f"{kind} must be a list of objects")
    return v


def validate_output(manifest: Manifest, out: Any) -> dict[str, Any]:
    """Shape-check a plugin result; only kinds the manifest declares. Returns a clean copy."""
    if not isinstance(out, dict):
        raise _bad_output("result must be a JSON object")
    clean: dict[str, Any] = {}
    for kind, value in out.items():
        if kind not in OUTPUT_KINDS:
            raise _bad_output(f"unknown output {kind!r}")
        if value is None:
            continue
        if kind not in manifest.outputs:
            raise _bad_output(f"returned {kind}, which the plugin does not declare")
    if out.get("images") is not None:
        images = []
        for x in _list_of_dicts(out, "images"):
            data, caption = x.get("data_b64"), x.get("caption", "")
            if not isinstance(data, str) or not isinstance(caption, str):
                raise _bad_output("each image needs data_b64 and a text caption")
            try:
                base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise _bad_output("image data_b64 is not base64") from None
            images.append({"data_b64": data, "caption": caption})
        clean["images"] = images
    if out.get("notes") is not None:
        notes = []
        for x in _list_of_dicts(out, "notes"):
            if not isinstance(x.get("text"), str) or not x["text"].strip():
                raise _bad_output("each note needs text")
            notes.append({"text": x["text"]})
        clean["notes"] = notes
    if out.get("attributes") is not None:
        attrs = []
        for x in _list_of_dicts(out, "attributes"):
            item_id, key, value = x.get("item_id"), x.get("key"), x.get("value")
            if not isinstance(item_id, str) or not isinstance(key, str) or not key.strip():
                raise _bad_output("each attribute needs item_id and key")
            ok = _scalar(value) or (isinstance(value, list) and all(map(_scalar, value)))
            if not ok:
                raise _bad_output(f"attribute {key!r} value must be text, a number or a list")
            a: dict[str, Any] = {"item_id": item_id, "key": key, "value": value}
            if x.get("label") is not None:
                if not isinstance(x["label"], str):
                    raise _bad_output(f"attribute {key!r} label must be text")
                a["label"] = x["label"]
            if isinstance(x.get("confidence"), int | float) and not isinstance(
                x["confidence"], bool
            ):
                a["confidence"] = max(0.0, min(1.0, float(x["confidence"])))
            attrs.append(a)
        clean["attributes"] = attrs
    if out.get("text") is not None:
        if not isinstance(out["text"], str):
            raise _bad_output("text must be a string")
        clean["text"] = out["text"]
    if out.get("table") is not None:
        t = out["table"]
        cols = t.get("columns") if isinstance(t, dict) else None
        rows = t.get("rows") if isinstance(t, dict) else None
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            raise _bad_output("table needs a list of column names")
        if not isinstance(rows, list) or not all(
            isinstance(r, list) and len(r) == len(cols) and all(map(_scalar_or_none, r))
            for r in rows
        ):
            raise _bad_output("table rows must be lists as long as the columns")
        clean["table"] = {"columns": cols, "rows": rows}
    return clean


def _scalar_or_none(v: Any) -> bool:
    return v is None or _scalar(v)


# ---- python runner -------------------------------------------------------------------------


def _image_paths_to_b64(out: Any, tmp: Path) -> Any:
    """A python plugin may return images as files it wrote in its temp dir."""
    if not isinstance(out, dict) or not isinstance(out.get("images"), list):
        return out
    root = tmp.resolve()
    images = []
    for x in out["images"]:
        if isinstance(x, dict) and "data_b64" not in x and isinstance(x.get("path"), str):
            target = (root / x["path"]).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise _bad_output(f"image path {x['path']!r} is not a file in the run folder")
            x = {**{k: v for k, v in x.items() if k != "path"},
                 "data_b64": base64.b64encode(target.read_bytes()).decode()}  # fmt: skip
        images.append(x)
    return {**out, "images": images}


def _run_python(
    p: Plugin, inputs: list[RunInput], params: dict[str, Any], board: BoardCtx,
    settings: Settings, progress: Callable[[str], None],
) -> Any:  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="muse-plugin-") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "in").mkdir()
        payload_inputs = []
        for n, i in enumerate(inputs):
            path = None
            if i.image is not None:
                name = i.id if SAFE_ID.match(i.id) else f"input-{n}"
                f = tmp / "in" / f"{name}.png"
                f.write_bytes(i.image)
                f.chmod(0o444)
                path = str(f)
            payload_inputs.append({"id": i.id, "kind": i.kind, "label": i.label,
                                   "attributes": i.attributes, "note_text": i.note_text,
                                   "image_path": path})  # fmt: skip
        request = json.dumps({
            "inputs": payload_inputs, "params": params,
            "board": {"title": board.title, "context": board.context, "notes": board.notes},
        }).encode()  # fmt: skip
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": tmpdir, "PYTHONHASHSEED": "0"}
        progress(f"Running {p.manifest.name}")
        proc = subprocess.Popen(
            [sys.executable, "-I", str(SHIM), str(p.folder)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=tmpdir, env=env, start_new_session=True,
        )  # fmt: skip
        assert proc.stdin and proc.stdout and proc.stderr
        stdout = bytearray()
        stderr = bytearray()
        too_large = threading.Event()

        def feed() -> None:
            try:
                proc.stdin.write(request)  # type: ignore[union-attr]
                proc.stdin.close()  # type: ignore[union-attr]
            except (BrokenPipeError, OSError):
                pass

        def read_out() -> None:
            while chunk := proc.stdout.read(65536):  # type: ignore[union-attr]
                stdout.extend(chunk)
                if len(stdout) > MAX_STDOUT:
                    too_large.set()
                    _kill_quietly(proc)
                    return

        def read_err() -> None:
            while chunk := proc.stderr.read(65536):  # type: ignore[union-attr]
                stderr.extend(chunk)
                if len(stderr) > STDERR_TAIL * 4:
                    del stderr[: len(stderr) - STDERR_TAIL]

        threads = [threading.Thread(target=t, daemon=True) for t in (feed, read_out, read_err)]
        for t in threads:
            t.start()
        timed_out = False
        try:
            proc.wait(timeout=settings.PLUGIN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # on every path: kill the whole group, so a background grandchild holding the pipes
            # neither outlives the run nor keeps the readers blocked
            _kill_quietly(proc)
            proc.wait()
            for t in threads:
                t.join(timeout=5)
            for s in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    s.close()
                except OSError:  # stdin after a broken pipe
                    pass
        if timed_out:
            raise PluginError(
                "PLUGIN_TIMEOUT", f"{p.manifest.name} ran longer than {settings.PLUGIN_TIMEOUT_S} s"
            )
        if too_large.is_set():
            raise _bad_output("output too large (over 1 MB)")
        tail = bytes(stderr[-STDERR_TAIL:]).decode("utf-8", "replace").strip()
        if proc.returncode == SHIM_BAD_RESULT_EXIT:
            raise _bad_output(f"{p.manifest.name} returned something that is not JSON: {tail}")
        if proc.returncode != 0:
            raise PluginError("PLUGIN_CRASHED", f"{p.manifest.name} crashed: {tail or 'no output'}")
        try:
            out = json.loads(bytes(stdout))
        except ValueError:
            raise _bad_output(f"{p.manifest.name} printed output that is not JSON") from None
        return _image_paths_to_b64(out, tmp)


def _kill_quietly(proc: subprocess.Popen[bytes]) -> None:
    """SIGKILL the plugin's process group (its children too); nothing left is fine."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # pgid == pid: start_new_session=True
    except (ProcessLookupError, PermissionError, AttributeError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


# ---- llm runner ----------------------------------------------------------------------------

_TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def render_prompt(
    template: str, params: dict[str, Any], inputs: list[RunInput], board: BoardCtx
) -> str:
    notes = [i.note_text for i in inputs if i.note_text] + list(board.notes)

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "notes":
            return "\n".join(notes)
        if name == "board.title":
            return board.title
        if name == "board.context":
            return board.context or ""
        if name.startswith("params."):
            v = params.get(name.removeprefix("params."))
            return "" if v is None else str(v)
        return m.group(0)

    return _TOKEN.sub(sub, template)


def _note_from(x: Any) -> Any:
    if isinstance(x, str):
        return {"text": x}
    if isinstance(x, dict) and isinstance(x.get("text"), str):
        tag = x.get("verdict") or x.get("label")
        return {"text": f"{tag}: {x['text']}" if isinstance(tag, str) and tag else x["text"]}
    return x


def map_llm_output(m: Manifest, raw: dict[str, Any]) -> dict[str, Any]:
    """Pick the declared outputs out of the schema-shaped answer via `output_map` (output kind ->
    answer key); without a map the answer must already be keyed by output kinds."""
    if not m.output_map:
        return raw
    out: dict[str, Any] = {}
    for kind, src in m.output_map.items():
        if src not in raw:
            continue
        v = raw[src]
        out[kind] = [_note_from(x) for x in v] if kind == "notes" and isinstance(v, list) else v
    return out


def _run_llm(
    p: Plugin, inputs: list[RunInput], params: dict[str, Any], board: BoardCtx,
    settings: Settings, progress: Callable[[str], None],
) -> Any:  # fmt: skip
    m = p.manifest
    assert m.prompt and m.output_schema is not None
    template = (p.folder / m.prompt).read_text(encoding="utf-8")
    prompt = render_prompt(template, params, inputs, board)
    images = [i.image for i in inputs if i.image is not None][:MAX_STRUCTURED_IMAGES]
    progress(f"Asking the model for {m.name}")
    try:
        raw = get_reasoning(settings).structured(images, m.output_schema, prompt)
    except ModelError as e:
        raise PluginError("PLUGIN_MODEL_FAILED", f"the model failed: {e.message}") from None
    return map_llm_output(m, raw)


# ---- model runner --------------------------------------------------------------------------


def _model_prompt(params: dict[str, Any], inputs: list[RunInput]) -> str:
    prompt = str(params.get("prompt") or "").strip()
    notes = [i.note_text.strip() for i in inputs if i.note_text and i.note_text.strip()]
    part = str(params.get("part") or "").strip()
    if params.get("mode", "part") == "part" and part:
        body = prompt or " ".join(notes)
        if not body:
            raise _bad_input("write a prompt or connect a note")
        return PART_PROMPT.format(part=part, prompt=body.rstrip(" ."))
    whole = "\n".join(x for x in [prompt, *notes] if x)
    if not whole:
        raise _bad_input("write a prompt or connect a note")
    return whole


def _run_model(
    p: Plugin, inputs: list[RunInput], params: dict[str, Any], board: BoardCtx,
    settings: Settings, progress: Callable[[str], None],
) -> Any:  # fmt: skip
    m = p.manifest
    if m.model not in ("image.edit", "image.generate"):
        raise PluginError("PLUGIN_NOT_CONNECTED", f"the {m.name} model is not connected")
    prompt = _model_prompt(params, inputs)
    count = max(1, int(params.get("count") or 1))  # results per input image
    sources = [i.image for i in inputs if i.image is not None] if m.model == "image.edit" else []
    jobs: list[bytes | None] = (
        [s for s in sources for _ in range(count)] if sources else [None] * count
    )
    jobs = jobs[:MAX_IMAGE_RESULTS]
    provider = get_image_provider(settings)
    images = []
    try:
        for n, src in enumerate(jobs, 1):
            if src is None:
                progress(f"Generating image {n} of {len(jobs)}")
                images.append(provider.generate(prompt))
            else:
                progress(f"Editing image {n} of {len(jobs)}")
                images.append(provider.edit(src, prompt))
    except ModelError as e:
        raise PluginError("PLUGIN_MODEL_FAILED", f"the image model failed: {e.message}") from None
    caption = prompt if len(prompt) <= 200 else prompt[:199] + "…"
    return {"images": [{"data_b64": base64.b64encode(b).decode(), "caption": caption}
                       for b in images]}  # fmt: skip


# ---- entry point ---------------------------------------------------------------------------

RUNNERS = {"python": _run_python, "llm": _run_llm, "model": _run_model}


def run_plugin(
    plugin: Plugin,
    inputs: list[RunInput],
    params: dict[str, Any],
    board: BoardCtx,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    """Run one plugin to a validated result; raises PluginError."""
    settings = get_settings()
    m = plugin.manifest
    if status(plugin, settings) == "not_connected":
        raise PluginError("PLUGIN_NOT_CONNECTED", f"{m.name} is not connected")
    check_inputs(m, inputs)
    params = check_params(m, params)
    out = validate_output(m, RUNNERS[m.runner](plugin, inputs, params, board, settings, progress))
    ids = {i.id for i in inputs}
    for a in out.get("attributes", []):
        if a["item_id"] not in ids:
            raise _bad_output(f"attribute {a['key']!r} is for an item that is not an input")
    return out
