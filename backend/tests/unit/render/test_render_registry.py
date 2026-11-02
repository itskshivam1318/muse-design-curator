"""renderers_for and pick_renderer: built-ins by content type, then board-added plugins."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.models import Board, BoardItem, BoardPlugin, ItemAttribute, ItemPart
from app.errors import AppError
from app.plugins import registry as plugin_registry
from app.plugins.manifest import Manifest
from app.plugins.registry import Plugin
from app.render import registry
from app.render.registry import pick_renderer, renderers_for
from app.render.rewrite import rewrite_passage


def board(session: Session) -> Board:
    b = Board(title="B", domain="watch")
    session.add(b)
    session.flush()
    return b


def item(session: Session, b: Board, kind: str, content_type: str | None) -> BoardItem:
    i = BoardItem(board_id=b.id, kind=kind, origin="upload", content_type=content_type)
    session.add(i)
    session.flush()
    return i


def dim(session: Session, i: BoardItem, key: str, part: str | None = None) -> ItemAttribute:
    row = ItemAttribute(
        item_id=i.id, key=key, label=key.title(), category="style", kind="text", part=part,
        confidence=0.8, status="model", source="ai",
        dim_type="physical" if part else "abstract", prompt=None if part else "What?",
    )  # fmt: skip
    session.add(row)
    session.flush()
    return row


def part(session: Session, i: BoardItem, key: str, label: str, region_kind: str) -> None:
    session.add(ItemPart(item_id=i.id, key=key, label=label, region_kind=region_kind, source="ai"))
    session.flush()


def ids(infos: list[Any]) -> list[str]:
    return [r.id for r in infos]


def test_renderers_for_text_is_spark_rewrite(session: Session) -> None:
    b = board(session)
    note = item(session, b, "note", "text")
    assert ids(renderers_for(session, note, dim(session, note, "tone"))) == ["spark_rewrite"]


def test_text_details(session: Session) -> None:
    b = board(session)
    note = item(session, b, "note", "text")
    part(session, note, "opening", "Opening", "text_range")
    (r,) = renderers_for(session, note, dim(session, note, "opening_tone", "opening"))
    assert (r.title, r.detail, r.builtin) == (
        "Rewrite passage",
        "Muse Spark · this passage only",
        True,
    )
    (r,) = renderers_for(session, note, dim(session, note, "tone"))
    assert r.detail == "Muse Spark · whole text"


def test_renderer_detail_names_part(session: Session) -> None:
    b = board(session)
    img = item(session, b, "image", "image")
    part(session, img, "hands", "Hands", "mask")
    (r,) = renderers_for(session, img, dim(session, img, "hand_style", "hands"))
    assert (r.id, r.title, r.builtin) == ("muse_image", "Generate image", True)
    assert r.detail == "Muse Image · inside the Hands mask"


def test_ui_physical_detail_is_a_box(session: Session) -> None:
    b = board(session)
    ui = item(session, b, "image", "ui")
    part(session, ui, "header", "Header", "box")
    (r,) = renderers_for(session, ui, dim(session, ui, "header_colour", "header"))
    assert r.detail == "Muse Image · inside the Header box"


def test_abstract_detail_says_no_mask(session: Session) -> None:
    b = board(session)
    img = item(session, b, "image", "image")
    (r,) = renderers_for(session, img, dim(session, img, "medium"))
    assert r.detail == "Muse Image · whole image, no mask"


def test_unanalysed_item_falls_back_on_its_kind(session: Session) -> None:
    b = board(session)
    assert ids(renderers_for(session, item(session, b, "image", None), None)) == ["muse_image"]
    assert ids(renderers_for(session, item(session, b, "note", None), None)) == ["spark_rewrite"]
    assert renderers_for(session, item(session, b, "link", None), None) == []


def _fake_plugin(monkeypatch: pytest.MonkeyPatch, **over: Any) -> None:
    raw = {
        "id": "shade", "name": "Shade", "description": "d", "mark": "S", "tint": "#fff",
        "ink": "#000", "runner": "python", "runs_on": "Local", "entry": "run.py",
        "inputs": {"kinds": ["image"]}, "outputs": ["images"], "renders": ["image"], **over,
    }  # fmt: skip
    plugins = dict(plugin_registry.get_registry())
    plugins["shade"] = Plugin(Manifest.model_validate(raw), Path("."), False)
    monkeypatch.setattr(registry, "get_registry", lambda: plugins)


def test_board_added_plugin_follows_the_builtins(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_plugin(monkeypatch)
    b = board(session)
    img = item(session, b, "image", "image")
    row = dim(session, img, "medium")
    assert ids(renderers_for(session, img, row)) == ["muse_image"]  # not added to this board
    session.add(BoardPlugin(board_id=b.id, plugin_id="shade"))
    session.add(BoardPlugin(board_id=b.id, plugin_id="image"))  # a built-in: not listed twice
    session.flush()
    infos = renderers_for(session, img, row)
    assert ids(infos) == ["muse_image", "plugin:shade"]
    assert (infos[1].title, infos[1].detail, infos[1].builtin) == ("Shade", "Local", False)
    note = item(session, b, "note", "text")
    assert ids(renderers_for(session, note, None)) == ["spark_rewrite"]  # renders images only


def test_pick_defaults_to_the_first_and_rejects_unknown(session: Session) -> None:
    b = board(session)
    img = item(session, b, "image", "image")
    assert pick_renderer(session, img, None, None).id == "muse_image"
    with pytest.raises(AppError) as e:
        pick_renderer(session, img, None, "spark_rewrite")
    assert (e.value.status, e.value.code) == (400, "RENDERER_NOT_FOUND")
    with pytest.raises(AppError) as e:
        pick_renderer(session, item(session, b, "link", None), None, None)
    assert (e.value.status, e.value.code) == (400, "NO_RENDERER")


def test_pick_a_plugin_that_cannot_edit_is_unsupported(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_plugin(monkeypatch)
    b = board(session)
    img = item(session, b, "image", "image")
    session.add(BoardPlugin(board_id=b.id, plugin_id="shade"))
    session.flush()
    with pytest.raises(AppError) as e:
        pick_renderer(session, img, None, "plugin:shade")
    assert (e.value.status, e.value.code) == (400, "RENDERER_UNSUPPORTED")


def test_rewrite_changes_only_range() -> None:
    out = rewrite_passage("Aaa. Bbb. Ccc.", (5, 9), "louder")
    assert out[:5] == "Aaa. " and out.endswith(" Ccc.")
    assert out == "Aaa. BBB. Ccc."


def test_rewrite_whole_text_without_range() -> None:
    assert rewrite_passage("quiet words", None, "louder") == "QUIET WORDS"  # the mock upper-cases


def test_shape_follows_the_part_region_kind(session: Session) -> None:
    b = board(session)
    img = item(session, b, "image", "image")
    part(session, img, "label", "Label", "box")  # a box part on a photo
    (r,) = renderers_for(session, img, dim(session, img, "label_colour", "label"))
    assert r.detail == "Muse Image · inside the Label box"


def test_a_row_with_a_part_is_physical_whatever_its_stored_type(session: Session) -> None:
    b = board(session)
    img = item(session, b, "image", "image")
    part(session, img, "hands", "Hands", "mask")
    row = dim(session, img, "hand_style", "hands")
    row.dim_type = "abstract"  # a legacy lens row
    (r,) = renderers_for(session, img, row)
    assert r.detail == "Muse Image · inside the Hands mask"
