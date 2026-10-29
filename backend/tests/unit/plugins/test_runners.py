import base64
import io
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.plugins import runners
from app.plugins.manifest import load_manifest
from app.plugins.registry import BUILTIN_DIR, Plugin
from app.plugins.runners import BoardCtx, PluginError, RunInput, run_plugin, validate_output
from app.providers.reliability import ModelError
from tests.media import image_bytes

BOARD = BoardCtx(title="Chairs", context="Calm oak chairs", notes=["no chrome"])


def py_plugin(
    tmp_path: Path, body: str, *, outputs: list[str] | None = None, **over: Any
) -> Plugin:
    d = tmp_path / "plug"
    d.mkdir(parents=True)
    (d / "main.py").write_text(body)
    data = {
        "id": "demo", "name": "Demo", "description": "x", "mark": "D", "tint": "#fff",
        "ink": "#000", "runner": "python", "runs_on": "Python",
        "inputs": {"kinds": ["image", "note"]}, "outputs": outputs or ["notes", "text"],
        "entry": "main.py", **over,
    }  # fmt: skip
    (d / "plugin.json").write_text(json.dumps(data))
    return Plugin(load_manifest(d, builtin=False), d, False)


def builtin(pid: str) -> Plugin:
    return Plugin(load_manifest(BUILTIN_DIR / pid, builtin=True), BUILTIN_DIR / pid, True)


def note(i: str = "n1", text: str = "softer edges") -> RunInput:
    return RunInput(id=i, kind="note", label="Note", attributes={}, note_text=text, image=None)


def img(i: str = "i1", seed: int = 0) -> RunInput:
    return RunInput(
        id=i, kind="image", label="Chair", attributes={"material": "oak"}, note_text=None,
        image=image_bytes(size=(64, 48), seed=seed),
    )  # fmt: skip


def run(p: Plugin, inputs: list[RunInput], params: dict[str, Any] | None = None) -> dict[str, Any]:
    seen: list[str] = []
    return run_plugin(p, inputs, params or {}, BOARD, seen.append)


def code(e: pytest.ExceptionInfo[PluginError]) -> str:
    return e.value.code


# ---- python runner -------------------------------------------------------------------------


def test_python_plugin_roundtrip(tmp_path: Path) -> None:
    p = py_plugin(
        tmp_path,
        (
            "import sys, os\n"
            "import numpy, PIL, sklearn\n"
            "def run(inputs, params, ctx):\n"
            "    print('noise on stdout is not the result')\n"
            "    ok = [os.path.isfile(i['image_path']) for i in inputs if i['image_path']]\n"
            "    return {'notes': [{'text': f\"{i['kind']}:{i['label']}:{i['note_text']}\"}\n"
            "                      for i in inputs],\n"
            "            'text': f\"{ctx['board']['title']}|{params['n']}|{ok}|\"\n"
            "                    f\"{sys.flags.isolated}|{inputs[1]['attributes']['material']}\"}\n"
        ),
        params={"type": "object", "properties": {"n": {"type": "integer", "default": 2}}},
    )
    out = run(p, [note(), img()])
    assert out["notes"] == [{"text": "note:Note:softer edges"}, {"text": "image:Chair:None"}]
    assert out["text"] == "Chairs|2|[True]|1|oak"


def test_python_plugin_image_path_output(tmp_path: Path) -> None:
    p = py_plugin(
        tmp_path,
        (
            "from PIL import Image\n"
            "def run(inputs, params, ctx):\n"
            "    Image.new('RGB', (4, 4), (9, 9, 9)).save('out.png')\n"
            "    return {'images': [{'path': 'out.png', 'caption': 'grey'}]}\n"
        ),
        outputs=["images"],
    )
    out = run(p, [img()])
    data = base64.b64decode(out["images"][0]["data_b64"])
    assert Image.open(io.BytesIO(data)).size == (4, 4)
    assert out["images"][0]["caption"] == "grey"


def test_python_plugin_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUGIN_TIMEOUT_S", "1")
    p = py_plugin(tmp_path, "import time\ndef run(inputs, params, ctx):\n    time.sleep(5)\n")
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_TIMEOUT"
    # the runner is left in a clean state: the next run on the same settings works
    ok = py_plugin(tmp_path / "next", "def run(inputs, params, ctx):\n    return {'text': 'ok'}\n")
    assert run(ok, [note()]) == {"text": "ok"}


def test_python_plugin_background_child_is_killed(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    p = py_plugin(
        tmp_path,
        "import subprocess, sys\n"
        "def run(inputs, params, ctx):\n"
        "    # inherits the shim's stdout/stderr pipes and outlives the plugin process\n"
        "    c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "    open(params['pidfile'], 'w').write(str(c.pid))\n"
        "    return {'text': 'done'}\n",
        params={"type": "object", "properties": {"pidfile": {"type": "string"}}},
    )
    start = time.monotonic()
    assert run(p, [note()], {"pidfile": str(pidfile)}) == {"text": "done"}
    assert time.monotonic() - start < 4
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, 9)
        pytest.fail("background child of the plugin survived the run")


def test_python_plugin_crash_reports_stderr(tmp_path: Path) -> None:
    p = py_plugin(tmp_path, "def run(inputs, params, ctx):\n    raise ValueError('bad oak')\n")
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_CRASHED"
    assert "bad oak" in e.value.message
    assert len(e.value.message) < 4096 + 200


def test_python_plugin_non_json_output(tmp_path: Path) -> None:
    p = py_plugin(tmp_path, "def run(inputs, params, ctx):\n    return {1, 2}\n")
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_BAD_OUTPUT"


def test_python_plugin_result_not_object(tmp_path: Path) -> None:
    p = py_plugin(tmp_path, "def run(inputs, params, ctx):\n    return [1]\n")
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_BAD_OUTPUT"


def test_python_plugin_output_too_large(tmp_path: Path) -> None:
    p = py_plugin(tmp_path, "def run(inputs, params, ctx):\n    return {'text': 'x' * 2_000_000}\n")
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_BAD_OUTPUT"
    assert "output too large" in e.value.message


def test_python_env_is_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSE_SECRET_KEY", "s3cret")
    monkeypatch.setenv("META_API_TOKEN", "t0ken")
    monkeypatch.setenv("PYTHONPATH", "/nowhere")
    p = py_plugin(
        tmp_path,
        (
            "import os\n"
            "def run(inputs, params, ctx):\n"
            "    return {'text': ','.join(sorted(os.environ)), 'notes': [{'text': os.environ['HOME']},\n"
            "            {'text': os.getcwd()}]}\n"
        ),
    )
    out = run(p, [note()])
    keys = set(out["text"].split(","))
    assert {"PATH", "HOME", "PYTHONHASHSEED"} <= keys
    for k in keys:
        assert not any(w in k for w in ("KEY", "TOKEN", "SECRET"))
        assert not k.startswith(("MUSE_", "META_"))
    assert "PYTHONPATH" not in keys
    home, cwd = out["notes"][0]["text"], out["notes"][1]["text"]
    assert Path(home).resolve() == Path(cwd).resolve()
    assert not Path(home).exists()  # the temp dir is cleaned up after the run


# ---- validation ----------------------------------------------------------------------------


def test_output_kind_not_declared_rejected(tmp_path: Path) -> None:
    p = py_plugin(tmp_path, "def run(inputs, params, ctx):\n    return {'table': {}}\n")
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_BAD_OUTPUT"
    m = p.manifest
    with pytest.raises(PluginError):
        validate_output(m, {"images": [{"data_b64": "aGk=", "caption": ""}]})
    with pytest.raises(PluginError):
        validate_output(m, {"bogus": 1})
    with pytest.raises(PluginError):
        validate_output(m, {"notes": [{"text": 3}]})
    assert validate_output(m, {"notes": [{"text": "hi"}], "text": "t"}) == {
        "notes": [{"text": "hi"}],
        "text": "t",
    }


def test_validate_output_shapes() -> None:
    m = builtin("palette").manifest.model_copy(
        update={"outputs": ["images", "notes", "attributes", "text", "table"]}
    )
    good = {
        "images": [{"data_b64": base64.b64encode(b"png").decode()}],
        "attributes": [{"item_id": "i1", "key": "k", "value": 2}],
        "table": {"columns": ["a", "b"], "rows": [[1, "x"]]},
    }
    out = validate_output(m, good)
    assert out["images"] == [{"data_b64": good["images"][0]["data_b64"], "caption": ""}]
    assert out["attributes"] == [{"item_id": "i1", "key": "k", "value": 2}]
    for bad in (
        {"images": [{"data_b64": "%%%"}]},
        {"images": [{"caption": "no data"}]},
        {"attributes": [{"item_id": "i1", "key": "", "value": 1}]},
        {"attributes": [{"item_id": "i1", "key": "k", "value": {"x": 1}}]},
        {"table": {"columns": ["a"], "rows": [[1, 2]]}},
        {"text": ["not", "a", "string"]},
        {"notes": "not a list"},
    ):
        with pytest.raises(PluginError) as e:
            validate_output(m, bad)
        assert e.value.code == "PLUGIN_BAD_OUTPUT"


def test_attribute_for_unknown_item_rejected(tmp_path: Path) -> None:
    p = py_plugin(
        tmp_path,
        (
            "def run(inputs, params, ctx):\n"
            "    return {'attributes': [{'item_id': 'elsewhere', 'key': 'k', 'value': 1}]}\n"
        ),
        outputs=["attributes"],
    )
    with pytest.raises(PluginError) as e:
        run(p, [note()])
    assert code(e) == "PLUGIN_BAD_OUTPUT"


def test_input_kind_and_count_checked(tmp_path: Path) -> None:
    p = py_plugin(
        tmp_path, "def run(inputs, params, ctx):\n    return {}\n",
        inputs={"kinds": ["image"], "min": 1, "max": 2},
    )  # fmt: skip
    for inputs in ([], [note()], [img("a"), img("b"), img("c")]):
        with pytest.raises(PluginError) as e:
            run(p, inputs)
        assert code(e) == "PLUGIN_BAD_INPUT"
    assert run(p, [img()]) == {}


def test_params_defaults_and_bounds(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "minimum": 3, "maximum": 8, "default": 5},
            "mode": {"type": "string", "enum": ["part", "whole"], "default": "part",
                     "x-show-if": {"x": 1}},
            "ratio": {"type": "number", "minimum": 0, "maximum": 1},
            "loud": {"type": "boolean", "default": False},
            "name": {"type": "string"},
        },
        "required": ["name"],
    }  # fmt: skip
    p = py_plugin(
        tmp_path, "import json\ndef run(inputs, params, ctx):\n"
        "    return {'text': json.dumps(params, sort_keys=True)}\n", params=schema,
    )  # fmt: skip
    out = json.loads(run(p, [note()], {"name": "x"})["text"])
    assert out == {"count": 5, "mode": "part", "loud": False, "name": "x"}
    out = json.loads(run(p, [note()], {"name": "x", "count": 8, "ratio": 0.5})["text"])
    assert out["count"] == 8 and out["ratio"] == 0.5
    for bad in (
        {},  # required missing
        {"name": "x", "count": 9},
        {"name": "x", "count": 2},
        {"name": "x", "count": "5"},
        {"name": "x", "count": True},
        {"name": "x", "count": 4.5},
        {"name": "x", "mode": "half"},
        {"name": "x", "ratio": 2},
        {"name": "x", "loud": "yes"},
        {"name": 3},
    ):
        with pytest.raises(PluginError) as e:
            run(p, [note()], bad)
        assert code(e) == "PLUGIN_BAD_INPUT", bad


# ---- llm runner ----------------------------------------------------------------------------


class RecordingReasoning:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[list[bytes], dict[str, Any], str]] = []

    def structured(
        self, images: list[bytes], schema: dict[str, Any], prompt: str
    ) -> dict[str, Any]:
        self.calls.append((images, schema, prompt))
        return self.result


def test_llm_runner_renders_prompt_and_maps_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "tag"
    d.mkdir()
    (d / "prompt.md").write_text(
        "Board {{board.title}} ({{board.context}}). Tone {{params.tone}}.\nNotes:\n{{notes}}\n"
    )
    schema = builtin("critique").manifest.output_schema
    data = {
        "id": "tag", "name": "Tag", "description": "x", "mark": "T", "tint": "#fff",
        "ink": "#000", "runner": "llm", "runs_on": "Muse Spark",
        "inputs": {"kinds": ["image", "note"]}, "outputs": ["notes", "text"],
        "prompt": "prompt.md", "output_schema": schema,
        "output_map": {"notes": "points", "text": "summary"},
        "params": {"type": "object", "properties": {"tone": {"type": "string", "default": "dry"}}},
    }  # fmt: skip
    (d / "plugin.json").write_text(json.dumps(data))
    p = Plugin(load_manifest(d, builtin=False), d, False)
    fake = RecordingReasoning({
        "points": [{"verdict": "fits", "text": "oak reads calm"},
                   {"verdict": "misses", "text": "too glossy"}],
        "summary": "Mostly there.",
    })  # fmt: skip
    monkeypatch.setattr(runners, "get_reasoning", lambda settings: fake)
    i = img()
    out = run(p, [note(), i])
    images, sent_schema, prompt = fake.calls[0]
    assert images == [i.image]
    assert sent_schema == schema
    assert prompt == (
        "Board Chairs (Calm oak chairs). Tone dry.\nNotes:\nsofter edges\nno chrome\n"
    )
    assert out == {
        "notes": [{"text": "fits: oak reads calm"}, {"text": "misses: too glossy"}],
        "text": "Mostly there.",
    }


def test_critique_builtin_with_mock_provider() -> None:
    p = builtin("critique")
    assert p.manifest.output_map == {"notes": "points", "text": "summary"}
    out = run(p, [img(), note()])
    assert out["notes"] and all(
        n["text"].split(":")[0] in ("fits", "misses", "unclear") for n in out["notes"]
    )
    assert isinstance(out["text"], str) and out["text"]
    assert run(p, [img(), note()]) == out  # mock is deterministic


def test_llm_model_error_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def structured(self, *a: Any) -> dict[str, Any]:
            raise ModelError("MODEL_UNAVAILABLE", message="down")

    monkeypatch.setattr(runners, "get_reasoning", lambda settings: Boom())
    with pytest.raises(PluginError) as e:
        run(builtin("critique"), [note()])
    assert code(e) == "PLUGIN_MODEL_FAILED"


# ---- model runner --------------------------------------------------------------------------


class RecordingImages:
    def __init__(self) -> None:
        self.edits: list[str] = []
        self.gens: list[str] = []
        self.sources: list[bytes] = []

    def _png(self) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (2, 2)).save(buf, "PNG")
        return buf.getvalue()

    def edit(self, image: bytes, prompt: str) -> bytes:
        self.edits.append(prompt)
        self.sources.append(image)
        return self._png()

    def generate(self, prompt: str) -> bytes:
        self.gens.append(prompt)
        return self._png()


def test_model_runner_part_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = RecordingImages()
    monkeypatch.setattr(runners, "get_image_provider", lambda settings: fake)
    p = builtin("image")
    inputs = [img("a"), img("b", 1), img("c", 2)]
    out = run(p, inputs, {"mode": "part", "part": "legs", "prompt": "make them brass", "count": 2})
    want = "Change only the legs: make them brass. Keep everything else exactly the same."
    assert fake.edits == [want] * 6  # count = results per input image
    assert fake.sources == [i.image for i in inputs for _ in range(2)]
    assert len(out["images"]) == 6
    assert all(base64.b64decode(x["data_b64"]) for x in out["images"])


def test_model_runner_whole_appends_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = RecordingImages()
    monkeypatch.setattr(runners, "get_image_provider", lambda settings: fake)
    run(builtin("image"), [img(), note()], {"mode": "whole", "prompt": "make it dusk"})
    assert fake.edits == ["make it dusk\nsofter edges"]


def test_model_runner_generates_without_images(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = RecordingImages()
    monkeypatch.setattr(runners, "get_image_provider", lambda settings: fake)
    out = run(builtin("image"), [note()], {"mode": "whole", "prompt": "a stool", "count": 3})
    assert fake.gens == ["a stool\nsofter edges"] * 3 and not fake.edits
    assert len(out["images"]) == 3
    run(builtin("image"), [note()], {"mode": "whole", "prompt": "a stool"})  # default count 1
    assert len(fake.gens) == 4


def test_model_runner_caps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = RecordingImages()
    monkeypatch.setattr(runners, "get_image_provider", lambda settings: fake)
    inputs = [img("a"), img("b", 1), img("c", 2)]
    out = run(builtin("image"), inputs, {"mode": "whole", "prompt": "dusk", "count": 4})
    assert runners.MAX_IMAGE_RESULTS == 8
    assert len(fake.edits) == 8 and len(out["images"]) == 8
    assert fake.sources == [inputs[0].image] * 4 + [inputs[1].image] * 4


def test_model_runner_needs_a_prompt() -> None:
    with pytest.raises(PluginError) as e:
        run(builtin("image"), [img()], {"mode": "whole"})
    assert code(e) == "PLUGIN_BAD_INPUT"


def test_model_runner_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom(RecordingImages):
        def edit(self, image: bytes, prompt: str) -> bytes:
            raise ModelError("MODEL_TIMEOUT", message="slow")

    monkeypatch.setattr(runners, "get_image_provider", lambda settings: Boom())
    with pytest.raises(PluginError) as e:
        run(builtin("image"), [img()], {"prompt": "x", "mode": "whole"})
    assert code(e) == "PLUGIN_MODEL_FAILED"


def test_model_runner_mock_provider_end_to_end() -> None:
    out = run(builtin("image"), [img()], {"part": "seat", "prompt": "blue"})
    assert len(out["images"]) == 1


def test_video_not_connected() -> None:
    for pid in ("video", "mesh", "code"):
        with pytest.raises(PluginError) as e:
            run(builtin(pid), [img()])
        assert code(e) == "PLUGIN_NOT_CONNECTED", pid
