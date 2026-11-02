from typing import Any

import pytest
from sqlalchemy.orm import Session

from app import events
from app.analysis.analysers import ItemContent, build_prompt
from app.analysis.context import (
    accept_offer,
    board_context,
    decline_offer,
    dimension_offers,
    hints_for,
    refresh_learned,
)
from app.db.models import Exploration, ExploreOption
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo


def add_item(session: Session, board_id: str, n: int) -> str:
    item = items_repo.create(
        session, board_id=board_id, kind="image", origin="upload",
        sha256=f"sha{n}", storage_path=f"p{n}.png",
    )  # fmt: skip
    session.flush()
    return item.id


def add_attr(session: Session, item_id: str, key: str, value: Any = "x", **kw: Any) -> None:
    fields: dict[str, Any] = {
        "label": key.replace("_", " ").title(), "category": "abstract", "kind": "enum",
        "value_json": value, "confidence": 0.9, "status": "ai", "source": "model",
        "dim_type": "abstract", "prompt": f"What is the {key}?",
    }  # fmt: skip
    attrs_repo.upsert(session, item_id, key, **{**fields, **kw})


def test_offer_appears_at_two_items_not_one(session: Session) -> None:
    board = boards_repo.create(session, "B")
    a, b = add_item(session, board.id, 1), add_item(session, board.id, 2)
    add_attr(session, a, "mood")
    add_attr(session, a, "era")
    add_attr(session, b, "Mood".lower(), label="mood")  # same label, different case
    add_attr(session, a, "stale_dim", status="stale")
    add_attr(session, b, "stale_dim", status="stale")
    add_attr(session, a, "gone", removed=True)
    add_attr(session, b, "gone", removed=True)
    offers = dimension_offers(session, board.id)
    assert [(o.label.lower(), o.dim_type, o.kind, o.count, o.total) for o in offers] == [
        ("mood", "abstract", "enum", 2, 2)
    ]


def test_accept_then_hint_reaches_prompt(session: Session) -> None:
    board = boards_repo.create(session, "B")
    a, b = add_item(session, board.id, 1), add_item(session, board.id, 2)
    add_attr(session, a, "mood")
    add_attr(session, b, "mood")
    offer = dimension_offers(session, board.id)[0]
    accept_offer(session, board.id, offer.label, offer.dim_type, offer.kind)
    accept_offer(session, board.id, offer.label, offer.dim_type, offer.kind)  # idempotent
    assert dimension_offers(session, board.id) == []
    hints = hints_for(session, board.id, a)
    assert [d["label"] for d in hints.board_dimensions] == ["Mood"]
    assert hints.abstract_definitions == [{"label": "Mood", "prompt": "What is the mood?"}]
    prompt = build_prompt(ItemContent(item_id=a, kind="note", text="t"), "ctx", hints)
    assert "Mood" in prompt and "What is the mood?" in prompt


def test_declined_offer_not_shown_again(session: Session) -> None:
    board = boards_repo.create(session, "B")
    for n in (1, 2):
        add_attr(session, add_item(session, board.id, n), "mood")
    offer = dimension_offers(session, board.id)[0]
    decline_offer(session, board.id, offer.label, offer.dim_type, offer.kind)
    assert dimension_offers(session, board.id) == []
    assert hints_for(session, board.id, add_item(session, board.id, 3)).board_dimensions == []


def test_learned_lists_kept_and_rejected(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(events, "publish", lambda b, t, d: sent.append((b, t, d)))
    board = boards_repo.create(session, "Watches", context="quiet, tool-like")
    ids = [add_item(session, board.id, n) for n in range(4)]
    for i in ids:
        add_attr(session, i, "dial", "black", label="Dial colour")
    for i, v in zip(ids, ["round", "round", "cushion", "cushion"], strict=True):
        add_attr(session, i, "case", v, label="Case shape")
    add_attr(session, ids[0], "hand", "x", label="Hand style")
    expl = Exploration(board_id=board.id, item_id=ids[0], key="hand")
    session.add(expl)
    session.flush()
    for name, status in [("copper dauphine", "kept"), ("gilt", "dismissed"), ("x", "open")]:
        session.add(ExploreOption(exploration_id=expl.id, name=name, status=status))
    session.commit()
    lines = refresh_learned(session, board.id)
    session.commit()
    assert "Dial colour: black · 4 of 4" in lines
    assert "Case shape: cushion 2 · round 2" in lines or "Case shape: round 2 · cushion 2" in lines
    assert "Kept for Hand style: copper dauphine; not: gilt" in lines
    assert board_context(session, board.id).startswith("Board: Watches\nYour words: quiet")
    assert "What Muse has learned:\n- " in board_context(session, board.id)
    assert sent == [(board.id, "board.learned", {"learned": lines})]
    refresh_learned(session, board.id)
    session.commit()
    assert len(sent) == 1  # unchanged, not republished


def test_your_words_never_changed_by_refresh(session: Session) -> None:
    board = boards_repo.create(session, "B", context="my own words")
    for n in (1, 2, 3):
        add_attr(session, add_item(session, board.id, n), "mood", "calm")
    session.commit()
    refresh_learned(session, board.id)
    session.commit()
    session.expire_all()
    assert boards_repo.get(session, board.id).context == "my own words"  # type: ignore[union-attr]
    assert "Your words: my own words" in board_context(session, board.id)
