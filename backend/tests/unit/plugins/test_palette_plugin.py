import io
import re

import numpy as np
from PIL import Image

from app.plugins.manifest import load_manifest
from app.plugins.registry import BUILTIN_DIR, Plugin
from app.plugins.runners import BoardCtx, RunInput, run_plugin

HEX = re.compile(r"^#[0-9a-f]{6}$")


def stripes(colors: list[tuple[int, int, int]], w: int = 80, h: int = 40) -> bytes:
    arr = np.zeros((h, w, 3), np.uint8)
    band = w // len(colors)
    for i, c in enumerate(colors):
        arr[:, i * band : (i + 1) * band] = c
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


COLORS = [(200, 30, 30), (30, 160, 40), (20, 40, 200), (240, 220, 30), (20, 20, 20),
          (250, 250, 250), (140, 70, 160), (250, 140, 0)]  # fmt: skip


def test_palette_plugin_deterministic() -> None:
    p = Plugin(load_manifest(BUILTIN_DIR / "palette", builtin=True), BUILTIN_DIR / "palette", True)
    inputs = [
        RunInput(id="a", kind="image", label="A", attributes={}, note_text=None,
                 image=stripes(COLORS)),
        RunInput(id="b", kind="image", label="B", attributes={}, note_text=None,
                 image=stripes(COLORS[:4])),
    ]  # fmt: skip
    board = BoardCtx(title="t", context=None, notes=[])
    # this runs the plugin through the shim under `sys.executable -I` with a stripped env, so
    # it also proves the venv's numpy / Pillow / scikit-image / scikit-learn stay importable
    first = run_plugin(p, inputs, {"count": 3}, board, lambda s: None)
    second = run_plugin(p, inputs, {"count": 3}, board, lambda s: None)
    assert first == second

    [note] = first["notes"]
    assert note["text"].startswith("Palette: ")
    hexes = note["text"].removeprefix("Palette: ").split(", ")
    assert len(hexes) == 3 and all(HEX.match(h) for h in hexes)

    attrs = first["attributes"]
    assert [a["item_id"] for a in attrs] == ["a", "b"]
    for a in attrs:
        assert a["key"] == "palette" and a["label"] == "Palette"
        vals = a["value"].split(", ")
        assert len(vals) == 3 and all(HEX.match(h) for h in vals)

    default = run_plugin(p, inputs, {}, board, lambda s: None)  # default count 5
    assert len(default["notes"][0]["text"].removeprefix("Palette: ").split(", ")) == 5
    eight = run_plugin(p, inputs, {"count": 8}, board, lambda s: None)
    assert len(eight["attributes"][0]["value"].split(", ")) == 8
    assert len(eight["attributes"][1]["value"].split(", ")) == 4  # only 4 colours in image b
