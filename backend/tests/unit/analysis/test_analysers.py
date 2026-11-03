import io

import pytest
from PIL import Image

from app.analysis import analysers
from app.analysis.analysers import Hints, ItemContent, build_prompt, run_analyser


def _png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 130, 140)).save(buf, "PNG")
    return buf.getvalue()


def _img(w=800, h=800):
    return ItemContent(item_id="i1", kind="image", image=_png(w, h))


def _dim(**kw):
    base = {
        "key": "subject", "label": "Subject", "type": "abstract", "part": None,
        "prompt": "What is it?", "kind": "text", "value": "x", "confidence": 0.7,
    }  # fmt: skip
    return {**base, **kw}


class _Fake:
    def __init__(self, answer):
        self.answer = answer

    def structured(self, images, schema, prompt):
        return self.answer


def _fake(monkeypatch, answer):
    monkeypatch.setattr(analysers, "get_reasoning", lambda _s: _Fake(answer))


def test_note_is_text_with_ranges():
    a = run_analyser(
        ItemContent(item_id="n", kind="note", text="Warm field watch, legible."), "", Hints.empty()
    )
    assert a.content_type == "text"
    assert a.parts[0].region_kind == "text_range" and a.parts[0].region == [0, 26]
    assert {d.key for d in a.dimensions} == {"tone", "length"}


def test_square_image_has_mask_parts():
    a = run_analyser(_img(), "", Hints.empty())
    assert a.content_type == "image"
    assert [p.key for p in a.parts] == ["body", "detail"]
    assert all(p.region_kind == "mask" and p.region is None for p in a.parts)


def test_wide_image_is_ui_with_boxes():
    a = run_analyser(_img(1600, 900), "", Hints.empty())
    assert a.content_type == "ui"
    assert a.parts and all(p.region_kind == "box" for p in a.parts)


def test_bad_dimension_dropped_not_fatal(monkeypatch):
    _fake(monkeypatch, {
        "content_type": "image", "summary": "s",
        "parts": [{"key": "body", "label": "Body", "region_kind": "mask", "region": None}],
        "dimensions": [
            _dim(key="orphan", label="Orphan", type="physical", part=None),  # no part
            _dim(key="ghost", label="Ghost", type="physical", part="nowhere", kind="color"),
            _dim(label="Mood Level", key="Mood Level"),  # reformatted, kept
            _dim(key="ok", label="Ok", kind="color", type="physical", part="Body", value="#fff"),
        ],
    })  # fmt: skip
    a = run_analyser(_img(), "", Hints.empty())
    assert [(d.key, d.part) for d in a.dimensions] == [("mood_level", None), ("ok", "body")]


def test_text_drops_boxes_and_forces_type(monkeypatch):
    _fake(monkeypatch, {
        "content_type": "image", "summary": "",
        "parts": [
            {"key": "a", "label": "A", "region_kind": "box", "region": [0, 0, 1, 1]},
            {"key": "b", "label": "B", "region_kind": "text_range", "region": [2, 999]},
        ],
        "dimensions": [],
    })  # fmt: skip
    a = run_analyser(ItemContent(item_id="n", kind="note", text="hello world"), "", Hints.empty())
    assert a.content_type == "text"
    assert [(p.key, p.region) for p in a.parts] == [("b", [2, 11])]


def test_image_drops_text_range_parts(monkeypatch):
    _fake(monkeypatch, {
        "content_type": "image", "summary": "",
        "parts": [{"key": "a", "label": "A", "region_kind": "text_range", "region": [0, 3]}],
        "dimensions": [],
    })  # fmt: skip
    assert run_analyser(_img(), "", Hints.empty()).parts == []


def test_empty_answer_gives_empty_analysis(monkeypatch):
    _fake(monkeypatch, {"parts": [], "dimensions": []})
    a = run_analyser(_img(), "", Hints.empty())
    assert a.parts == [] and a.dimensions == [] and a.content_type == "image"


def test_truncates_to_limits(monkeypatch):
    _fake(monkeypatch, {
        "content_type": "image", "summary": "",
        "parts": [
            {"key": f"p{i}", "label": f"P{i}", "region_kind": "mask", "region": None}
            for i in range(12)
        ],
        "dimensions": [_dim(key=f"d{i}", label=f"D{i}") for i in range(30)],
    })  # fmt: skip
    a = run_analyser(_img(), "", Hints.empty())
    assert len(a.parts) == 8 and len(a.dimensions) == 20


def test_prompt_carries_reuse_and_removed():
    hints = Hints(
        board_dimensions=[{"label": "Medium"}],
        abstract_definitions=[{"label": "Mood", "prompt": "How does it feel?"}],
        removed=["strap_stitching"],
    )
    p = build_prompt(_img(), "a watch board", hints)
    assert "Medium" in p and "Mood" in p and "strap_stitching" in p and "a watch board" in p


def test_prompt_includes_note_text():
    p = build_prompt(ItemContent(item_id="n", kind="note", text="hi there"), "", Hints.empty())
    assert "hi there" in p and "text_range" in p


def test_load_content_rejects_unsupported():
    from app.db.models import BoardItem
    from app.errors import AppError

    with pytest.raises(AppError) as e:
        analysers.load_content(None, BoardItem(id="x", kind="link"))  # type: ignore[arg-type]
    assert e.value.code == "UNSUPPORTED_ITEM"


def test_image_part_keeps_its_rough_box_as_a_hint(monkeypatch):
    _fake(monkeypatch, {
        "content_type": "image", "summary": "s",
        "parts": [
            {"key": "rear_wheel", "label": "Rear wheel", "region_kind": "mask",
             "region": [0.6, 0.6, 0.75, 0.85]},
            {"key": "front_wheel", "label": "Front wheel", "region_kind": "mask",
             "region": [0.3, 0.6, 0.1, 0.85]},  # x0 > x1: no hint
            {"key": "glass", "label": "Glass", "region_kind": "mask", "region": [0.1, 0.2]},
        ],
        "dimensions": [],
    })  # fmt: skip
    a = run_analyser(_img(), "", Hints.empty())
    assert [(p.key, p.region) for p in a.parts] == [
        ("rear_wheel", [0.6, 0.6, 0.75, 0.85]), ("front_wheel", None), ("glass", None),
    ]  # fmt: skip
