"""Explore and its check work on the item's own dimensions, with or without a board lens."""

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.db.models import ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import explore as explore_repo
from app.domain.kinds import AttributeSpec, EnumSpec, TextSpec
from app.explore import check, service
from app.explore.check import check_generated
from app.ingest.common import ItemMeta
from app.ingest.images import ingest_image


def png(colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), colour).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def board(session: Session, data_dir: Path) -> str:
    return boards_repo.create(session, "Bags", context="soft leather, quiet hardware").id


def dim(
    session: Session, item_id: str, spec: AttributeSpec, value: Any, *, physical: bool, **over: Any
) -> None:
    fields = {
        "label": spec.label, "category": spec.category, "kind": spec.kind, "part": spec.part,
        "value_json": value, "confidence": 0.9, "status": "extracted", "source": "model",
        "dim_type": "physical" if physical else "abstract",
        "spec_json": spec.model_dump(mode="json"), **over,
    }  # fmt: skip
    attrs_repo.upsert(session, item_id, spec.key, **fields)


MOOD = TextSpec(key="mood", label="Mood", category="abstract")
STITCH = EnumSpec(key="strap_stitching", label="Strap stitching", category="physical",
                  part="strap", vocabulary=["contrast"], open_vocabulary=True)  # fmt: skip
HARDWARE = EnumSpec(key="hardware", label="Hardware", category="physical", part="clasp",
                    vocabulary=["brass"], open_vocabulary=True)  # fmt: skip


class Spy:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        return {"options": [{"name": "Hushed", "description": "Calmer.", "distance": "near",
                             "value": "hushed", "keeps": ["strap_stitching", "gone", "mood"],
                             "edit_prompt": "Make it hushed."}]}  # fmt: skip


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    s = Spy()
    monkeypatch.setattr(service, "get_reasoning", lambda _settings: s)
    return s


def test_abstract_prompt_reaches_model(session: Session, board: str, spy: Spy) -> None:
    item = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item
    dim(session, item.id, MOOD, "calm", physical=False,
        prompt="The feeling the whole bag gives off: calm, loud, playful.")  # fmt: skip
    dim(session, item.id, STITCH, "contrast", physical=True)
    dim(session, item.id, HARDWARE, "brass", physical=True, removed=True)

    _e, opts = service.explore(session, item.id, "mood", steer=None, parent_option_id=None,
                               mode="initial")  # fmt: skip

    p = spy.prompts[0]
    assert "The feeling the whole bag gives off: calm, loud, playful." in p
    assert "soft leather, quiet hardware" in p  # board context
    assert "- strap_stitching (Strap stitching): contrast" in p
    assert "- hardware (" not in p  # removed: not offered for keeps
    assert opts[0].keeps_json == ["strap_stitching"]


def test_physical_prompt_says_only_the_part_changes(session: Session, board: str, spy: Spy) -> None:
    item = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item
    session.add(ItemPart(item_id=item.id, key="strap", label="Shoulder strap",
                         region_kind="box", region_json=[0, 0, 1, 1], source="ai"))  # fmt: skip
    dim(session, item.id, STITCH, "contrast", physical=True)
    service.explore(session, item.id, "strap_stitching", steer=None, parent_option_id=None,
                    mode="initial")  # fmt: skip
    assert "only the Shoulder strap changes" in spy.prompts[0]


def test_removed_part_label_is_not_used(session: Session, board: str, spy: Spy) -> None:
    item = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item
    session.add(ItemPart(item_id=item.id, key="strap", label="Shoulder strap", removed=True,
                         region_kind="box", region_json=[0, 0, 1, 1], source="ai"))  # fmt: skip
    dim(session, item.id, STITCH, "contrast", physical=True)
    service.explore(session, item.id, "strap_stitching", steer=None, parent_option_id=None,
                    mode="initial")  # fmt: skip
    assert "Shoulder strap" not in spy.prompts[0] and "only the strap changes" in spy.prompts[0]


def test_stale_dimension_is_still_explorable(session: Session, board: str, spy: Spy) -> None:
    item = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item
    dim(session, item.id, MOOD, "calm", physical=False, prompt="How it feels.", status="stale")
    _e, opts = service.explore(session, item.id, "mood", steer=None, parent_option_id=None,
                               mode="initial")  # fmt: skip
    assert [o.name for o in opts] == ["Hushed"]


class Checker:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        return {"answer": "yes", "confidence": 0.9, "box": None, "note": "ok"}


def test_check_holds_items_own_dimensions(
    session: Session, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item.id
    gen = ingest_image(session, board, png((200, 20, 30)), ItemMeta(origin="generated")).item.id
    dim(session, src, MOOD, "calm", physical=False, prompt="How it feels.")
    dim(session, src, STITCH, "contrast", physical=True)  # held and kept
    dim(session, gen, STITCH, "contrast", physical=True)
    dim(session, src, HARDWARE, "brass", physical=True)  # held but drifted
    dim(session, gen, HARDWARE, "chrome", physical=True)
    colour = TextSpec(key="lining", label="Lining", category="physical", part="inside")
    dim(session, src, colour, "silk", physical=True)  # held, missing on the take -> unknown
    old = TextSpec(key="sheen", label="Sheen", category="abstract")
    dim(session, src, old, "matte", physical=False, prompt="x", status="stale")  # not held
    dim(session, gen, old, "glossy", physical=False, prompt="x")
    gone = TextSpec(key="trim", label="Trim", category="abstract")
    dim(session, src, gone, "piped", physical=False, prompt="x", removed=True)  # not held
    dim(session, gen, gone, "raw", physical=False, prompt="x")
    e = explore_repo.get_or_create(session, board, src, "mood")
    (o,) = explore_repo.add_options(session, e.id, [{
        "name": "Hushed", "description": "Calmer.", "distance": "near", "value_json": "hushed",
        "keeps_json": ["strap_stitching", "hardware", "lining", "sheen", "trim"],
        "edit_prompt": "Make it hushed.", "batch": 1,
    }])  # fmt: skip
    checker = Checker()
    monkeypatch.setattr(check, "get_reasoning", lambda _s: checker)

    got = check_generated(session, src, gen, o)

    assert (got["kept"], got["drifted"], got["of"], got["unknown"]) == (1, ["hardware"], 2, 1)
    assert "for its Mood" in checker.prompts[0]  # the label of the item's own dimension


def test_vocabulary_grows_the_items_own_closed_spec(session: Session, board: str) -> None:
    from app.analysis.spec import spec_for
    from app.explore.vocab import add_vocabulary

    item = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item.id
    closed = HARDWARE.model_copy(update={"open_vocabulary": False})
    dim(session, item, closed, "brass", physical=True)
    dim(session, item, STITCH, "contrast", physical=True)  # open: nothing to grow
    assert add_vocabulary(session, board, "hardware", "gunmetal", item_id=item) is True
    assert add_vocabulary(session, board, "hardware", "brass", item_id=item) is False
    assert add_vocabulary(session, board, "strap_stitching", "tonal", item_id=item) is False
    rows = {r.key: r for r in attrs_repo.for_item(session, item)}
    assert spec_for(rows["hardware"]).vocabulary == ["brass", "gunmetal"]  # type: ignore[union-attr]
    assert boards_repo.get(session, board).lens_id is None  # type: ignore[union-attr]
    rows["hardware"].removed = True  # a removed dimension's spec is never grown
    session.flush()
    assert add_vocabulary(session, board, "hardware", "copper", item_id=item) is False
    assert spec_for(rows["hardware"]).vocabulary == ["brass", "gunmetal"]  # type: ignore[union-attr]


def test_check_holds_dimensions_the_keeps_leave_out(
    session: Session, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item.id
    gen = ingest_image(session, board, png((200, 20, 30)), ItemMeta(origin="generated")).item.id
    dim(session, src, MOOD, "calm", physical=False, prompt="How it feels.")  # explored: not held
    dim(session, gen, MOOD, "hushed", physical=False, prompt="How it feels.")
    dim(session, src, HARDWARE, "brass", physical=True)  # not in keeps, drifts
    dim(session, gen, HARDWARE, "chrome", physical=True)
    e = explore_repo.get_or_create(session, board, src, "mood")
    (o,) = explore_repo.add_options(session, e.id, [{
        "name": "Hushed", "description": "", "distance": "near", "value_json": "hushed",
        "keeps_json": [], "edit_prompt": "Make it hushed.", "batch": 1,
    }])  # fmt: skip
    monkeypatch.setattr(check, "get_reasoning", lambda _s: Checker())
    got = check_generated(session, src, gen, o)
    assert (got["kept"], got["drifted"], got["of"], got["unknown"]) == (0, ["hardware"], 1, 0)
