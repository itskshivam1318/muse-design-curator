"""Notes: board items of kind "note", ignored by image work and read as reasoning context."""

from types import SimpleNamespace as NS

import pytest
from sqlalchemy.orm import Session

from app.board.profile import compute_profile
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.errors import AppError
from app.extraction import service as extraction
from app.lens_service import _eligible
from app.notes.service import board_notes_context, create_note, update_note_text


def test_create_note_defaults(session: Session) -> None:
    b = boards_repo.create(session, "B")
    n = create_note(session, b.id, "warm and quiet", 10, 20)
    assert (n.kind, n.origin, n.rights_status, n.parse_status) == (
        "note", "note", "user_supplied", "completed",
    )  # fmt: skip
    assert (n.w, n.h, n.x, n.y, n.note_text) == (220, 150, 10, 20, "warm and quiet")


def test_update_note_text_rejects_image(session: Session) -> None:
    b = boards_repo.create(session, "B")
    img = items_repo.create(session, board_id=b.id, kind="image", origin="upload")
    with pytest.raises(AppError) as e:
        update_note_text(session, img.id, "x")
    assert (e.value.status, e.value.code) == (400, "NOT_A_NOTE")


def test_update_note_text(session: Session) -> None:
    b = boards_repo.create(session, "B")
    n = create_note(session, b.id, "a", 0, 0)
    assert update_note_text(session, n.id, "b").note_text == "b"


def test_parse_item_skips_notes(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    b = boards_repo.create(session, "B")
    n = create_note(session, b.id, "a", 0, 0)
    session.commit()

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("reasoning provider must not be called for a note")

    monkeypatch.setattr(extraction, "get_reasoning", boom)
    extraction.parse_item(session, n.id)
    session.refresh(n)
    assert n.parse_status == "completed"


def test_profile_ignores_notes() -> None:
    def it(i: str, kind: str) -> NS:
        return NS(id=i, role="reference", embedding_json=None, kind=kind)

    items = [it("a", "image"), it("b", "image"), it("n", "note")]
    assert compute_profile(items, {}, None, {}).n_reference == 2


def test_lens_pool_ignores_notes(session: Session) -> None:
    b = boards_repo.create(session, "B")
    img = items_repo.create(session, board_id=b.id, kind="image", origin="upload",
                            parse_status="completed")  # fmt: skip
    create_note(session, b.id, "a", 0, 0)
    assert [i.id for i in _eligible(session, b.id)] == [img.id]


def test_notes_context_caps(session: Session) -> None:
    b = boards_repo.create(session, "B")
    for i in range(25):
        create_note(session, b.id, f"note {i:02d} " + "x" * 190, 0, 0)
    out = board_notes_context(session, b.id)
    assert len(out) <= 20 and sum(len(s) for s in out) <= 2000
    assert out[0].startswith("note 24")


def test_notes_context_skips_removed_and_empty(session: Session) -> None:
    b = boards_repo.create(session, "B")
    a = create_note(session, b.id, "keep", 0, 0)
    gone = create_note(session, b.id, "gone", 0, 0)
    blank = create_note(session, b.id, "  ", 0, 0)
    items_repo.soft_delete(session, gone.id)
    assert blank.id and board_notes_context(session, b.id) == ["keep"] and a.id
