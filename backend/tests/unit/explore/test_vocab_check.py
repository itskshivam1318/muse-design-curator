"""add_vocabulary grows a closed enum only; check_generated asks for the target, compares keeps."""

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.db.models import ExploreOption
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import explore as explore_repo
from app.db.repos import lenses as lenses_repo
from app.domain.lens import load_curated_lens
from app.explore import check
from app.explore.check import check_generated, clean_target
from app.explore.vocab import add_vocabulary
from app.ingest.common import ItemMeta
from app.ingest.images import ingest_image


def png(colour: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), colour).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def board(session: Session, data_dir: Path) -> str:
    lens = load_curated_lens("watch", shape_enabled=False)
    assert lens is not None
    b = boards_repo.create(session, "Watches", domain="watch")
    row = lenses_repo.save(session, b.id, "watch", "curated", lens.model_dump(mode="json"),
                           status="confirmed")  # fmt: skip
    b.lens_id = row.id
    session.flush()
    return b.id


def lens_vocab(session: Session, board_id: str, key: str) -> Any:
    b = boards_repo.get(session, board_id)
    assert b is not None and b.lens_id
    row = lenses_repo.get(session, b.lens_id)
    assert row is not None
    return next(a for a in row.spec_json["attributes"] if a["key"] == key).get("vocabulary")


def test_closed_enum_gets_the_new_token(session: Session, board: str) -> None:
    before = boards_repo.get(session, board).lens_id  # type: ignore[union-attr]
    assert add_vocabulary(session, board, "markers", "devanagari") is True
    b = boards_repo.get(session, board)
    assert b is not None and b.lens_id != before
    row = lenses_repo.get(session, b.lens_id)  # type: ignore[arg-type]
    assert row is not None and (row.origin, row.status, row.version) == ("edited", "confirmed", 2)
    assert row.spec_json["id"] == "watch@2" and row.spec_json["origin"] == "edited"
    assert lens_vocab(session, board, "markers")[-1] == "devanagari"
    assert lens_vocab(session, board, "markers")[:-1] == ["arabic", "roman", "baton", "dot",
                                                          "dauphine", "none"]  # fmt: skip
    assert "devanagari" not in lens_vocab(session, board, "hands")


def test_value_already_in_vocab_is_a_no_op(session: Session, board: str) -> None:
    before = boards_repo.get(session, board).lens_id  # type: ignore[union-attr]
    assert add_vocabulary(session, board, "markers", "roman") is False
    assert boards_repo.get(session, board).lens_id == before  # type: ignore[union-attr]


def test_open_vocab_unchanged(session: Session, board: str) -> None:
    before = boards_repo.get(session, board).lens_id  # type: ignore[union-attr]
    for key, value in [("case_material", "bronze"), ("dial_color", "burnt orange"),
                       ("has_date_window", True), ("legibility", "high"),
                       ("overall_style", "quiet_utility"), ("markers", None),
                       ("markers", "Not A Token"), ("not_a_key", "x")]:  # fmt: skip
        assert add_vocabulary(session, board, key, value) is False, key
    assert boards_repo.get(session, board).lens_id == before  # type: ignore[union-attr]
    assert len(lenses_repo.versions(session, board, "watch")) == 1


def test_board_without_lens_is_a_no_op(session: Session, data_dir: Path) -> None:
    b = boards_repo.create(session, "Empty")
    assert add_vocabulary(session, b.id, "markers", "devanagari") is False


# ---- check ----


def attr(session: Session, item_id: str, key: str, kind: str, value: Any, **over: Any) -> None:
    fields = {"label": key.title(), "category": "dial", "kind": kind, "part": None,
              "value_json": value, "confidence": 0.9, "status": "extracted", "source": "model",
              **over}  # fmt: skip
    attrs_repo.upsert(session, item_id, key, **fields)


class Checker:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.prompts: list[str] = []
        self.images: list[list[bytes]] = []

    def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.images.append(images)
        return self.answer


def make_option(session: Session, board_id: str, item_id: str, **over: Any) -> ExploreOption:
    e = explore_repo.get_or_create(session, board_id, item_id, "markers")
    row = {"name": "Devanagari numerals", "description": "Hindi numerals at each hour.",
           "distance": "near", "value_json": "devanagari", "keeps_json": [],
           "edit_prompt": "Change only Markers.", "batch": 1, **over}  # fmt: skip
    (o,) = explore_repo.add_options(session, e.id, [row])
    return o


@pytest.fixture
def pair(session: Session, board: str) -> tuple[str, str]:
    src = ingest_image(session, board, png((10, 20, 30)), ItemMeta()).item
    gen = ingest_image(session, board, png((200, 20, 30)), ItemMeta(origin="generated")).item
    return src.id, gen.id


YES = {"answer": "yes", "confidence": 0.82, "box": None, "note": "Hindi numerals."}


def test_check_counts_only_reliable_keeps(
    session: Session, board: str, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    src, gen = pair
    # hands: reliable on both, same -> kept
    attr(session, src, "hands", "enum", "baton")
    attr(session, gen, "hands", "enum", "baton")
    # case_finish: reliable on both, different -> drifted
    attr(session, src, "case_finish", "enum", "brushed")
    attr(session, gen, "case_finish", "enum", "polished")
    # bezel_style: unreliable on the source -> not counted at all
    attr(session, src, "bezel_style", "enum", "fluted", confidence=0.3)
    attr(session, gen, "bezel_style", "enum", "smooth")
    # dial_finish: reliable on source, generated value unreliable -> unknown: counted, neither
    attr(session, src, "dial_finish", "enum", "sunburst")
    attr(session, gen, "dial_finish", "enum", "matte", confidence=0.2)
    # strap_material: reliable on source, missing on the generated item -> unknown
    attr(session, src, "strap_material", "enum", "leather")
    # legibility: no source record -> not counted
    attr(session, gen, "legibility", "ordinal", "high")
    keeps = ["hands", "case_finish", "bezel_style", "dial_finish", "strap_material", "legibility"]
    o = make_option(session, board, src, keeps_json=keeps)
    checker = Checker(YES)
    monkeypatch.setattr(check, "get_reasoning", lambda _s: checker)

    got = check_generated(session, src, gen, o)

    assert got["kept"] == 1 and got["of"] == 4 and got["drifted"] == ["case_finish"]
    assert got["target"] == YES


def test_check_asks_about_the_generated_image(
    session: Session, board: str, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.repos import items as items_repo
    from app.storage import files

    src, gen = pair
    o = make_option(session, board, src)
    checker = Checker(YES)
    monkeypatch.setattr(check, "get_reasoning", lambda _s: checker)
    check_generated(session, src, gen, o)
    row = items_repo.get(session, gen)
    assert row is not None and row.storage_path
    assert checker.images == [[files.abs_path(row.storage_path).read_bytes()]]
    assert '"Devanagari numerals"' in checker.prompts[0] and "Markers" in checker.prompts[0]
    assert "Hindi numerals at each hour." in checker.prompts[0]


def test_check_tolerates_an_option_without_value(
    session: Session, board: str, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    src, gen = pair
    o = make_option(session, board, src, value_json=None, keeps_json=None)
    monkeypatch.setattr(check, "get_reasoning", lambda _s: Checker(YES))
    got = check_generated(session, src, gen, o)
    assert (got["kept"], got["of"], got["drifted"]) == (0, 0, [])


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (YES, YES),
        ({"answer": "YES", "confidence": 1.5, "box": [0, 0, 1, 1], "note": " x "},
         {"answer": "yes", "confidence": 1.0, "box": [0.0, 0.0, 1.0, 1.0], "note": "x"}),
        ({"answer": "maybe", "confidence": float("nan"), "box": [0.1, 0.2, 0.3], "note": 4},
         {"answer": "unclear", "confidence": None, "box": None, "note": ""}),
        ({"answer": "no", "confidence": "0.4", "box": [0.1, 0.2, 1.3, 0.4]},
         {"answer": "no", "confidence": None, "box": None, "note": ""}),
        ({"answer": "no", "confidence": True, "box": [True, 0.2, 0.3, 0.4]},
         {"answer": "no", "confidence": None, "box": None, "note": ""}),
        ("junk", {"answer": "unclear", "confidence": None, "box": None, "note": ""}),
    ],
)  # fmt: skip
def test_clean_target(raw: Any, want: dict[str, Any]) -> None:
    assert clean_target(raw) == want
