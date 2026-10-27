"""Auto lens: an Auto board whose items clearly vote for one curated domain gets that lens."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app import events, jobs
from app.board import profile as profile_mod
from app.db.models import BoardItem, CorpusItem
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo

WATCH, UI = [1.0, 0.0], [0.0, 1.0]


@pytest.fixture(autouse=True)
def corpus(session: Session, data_dir: Path) -> Iterator[None]:
    saved = dict(jobs._registry)
    data_dir.mkdir(parents=True, exist_ok=True)
    np.save(data_dir / "embeddings.npy", np.array([WATCH, [0.9, 0.1], UI, [0.1, 0.9]]))
    for row, domain in enumerate(["watch", "watch", "ui", "ui"]):
        session.add(
            CorpusItem(
                domain=domain, source="s", source_id=f"{domain}{row}", landing_url="u",
                image_url="u", license_code="x", attribution_text="a", embedding_row=row,
                indexing_status="indexed",
            )
        )  # fmt: skip
    session.flush()
    yield
    jobs._registry.clear()
    jobs._registry.update(saved)


def board_with(
    session: Session, embs: list[list[float]], domain: str | None = None
) -> tuple[str, list[BoardItem]]:
    board = boards_repo.create(session, "B", domain=domain)
    items = [
        items_repo.create(
            session, board_id=board.id, kind="image", origin="upload",
            parse_status="pending_lens", embedding_json=e,
        )
        for e in embs
    ]  # fmt: skip
    session.flush()
    return board.id, items


def test_auto_board_with_three_watch_items_gets_watch_lens(session: Session) -> None:
    queued: list[str] = []
    jobs.register("parse_item", lambda item_id: queued.append(item_id))
    bid, items = board_with(session, [WATCH, [0.95, 0.05], [0.9, 0.1]])
    with events.subscribe(bid) as sub:
        profile_mod.recompute(session, bid)
        session.commit()
        seen = [sub.get(timeout=1), sub.get(timeout=1)]
    board = boards_repo.get(session, bid)
    assert board is not None and board.domain == "watch" and board.lens_id
    assert sorted(queued) == sorted(i.id for i in items)
    kinds = {e["type"]: e for e in seen if e}
    assert set(kinds) == {"profile.updated", "board.updated"}
    assert kinds["board.updated"]["data"]["board"]["domain"] == "watch"


def test_mixed_board_stays_without_lens(session: Session) -> None:
    bid, _ = board_with(session, [WATCH, WATCH, UI, UI])
    profile_mod.recompute(session, bid)
    board = boards_repo.get(session, bid)
    assert board is not None and board.domain is None and board.lens_id is None
    from app.board.profile import BoardProfile
    from app.db.repos import profiles as profiles_repo

    row = profiles_repo.latest(session, bid)
    assert row is not None
    assert BoardProfile.model_validate(row.profile_json).domain_votes.mixed is True


def test_user_set_domain_is_never_changed(session: Session) -> None:
    bid, _ = board_with(session, [WATCH, WATCH, WATCH], domain="ui")
    profile_mod.recompute(session, bid)
    board = boards_repo.get(session, bid)
    assert board is not None and board.domain == "ui"


def test_fewer_than_three_items_do_nothing(session: Session) -> None:
    bid, _ = board_with(session, [WATCH, WATCH])
    profile_mod.recompute(session, bid)
    board = boards_repo.get(session, bid)
    assert board is not None and board.domain is None and board.lens_id is None
