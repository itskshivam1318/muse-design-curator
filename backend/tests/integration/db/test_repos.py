import inspect

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.repos import attributes, boards, corpus, decisions, items, lenses, profiles


def _board(session: Session) -> str:
    return boards.create(session, title="b", context="ctx").id


def test_migration_applies_to_an_empty_db(session: Session) -> None:
    tables = set(sa_inspect(session.get_bind()).get_table_names())
    expected = {
        "boards", "board_items", "item_frames", "item_attributes", "attribute_events",
        "lenses", "part_masks", "corpus_items", "corpus_attributes", "board_profiles",
        "variation_runs", "run_candidates", "validation_results", "decisions",
        "model_cache", "idempotency_keys", "extension_tokens",
    }  # fmt: skip
    assert expected <= tables


def test_ids_are_prefixed_lowercase_ulids(session: Session) -> None:
    b = boards.create(session, title="t", context="")
    assert b.id.startswith("brd_") and b.id == b.id.lower() and len(b.id) == 4 + 26
    assert b.created_at.endswith("+00:00") or b.created_at.endswith("Z")


def test_duplicate_active_sha256_rejected_allowed_after_soft_delete_and_other_board(
    session: Session,
) -> None:
    b1, b2 = _board(session), _board(session)
    first = items.create(session, board_id=b1, kind="image", origin="upload", sha256="aa")
    with pytest.raises(IntegrityError), session.begin_nested():
        items.create(session, board_id=b1, kind="image", origin="drop", sha256="aa")
    items.create(session, board_id=b2, kind="image", origin="upload", sha256="aa")
    items.soft_delete(session, first.id)
    again = items.create(session, board_id=b1, kind="image", origin="upload", sha256="aa")
    assert again.id != first.id
    # null sha256 (links) never conflict
    items.create(session, board_id=b1, kind="link", origin="link")
    items.create(session, board_id=b1, kind="link", origin="link")


def test_item_positions_persist_and_update(session: Session) -> None:
    b = _board(session)
    it = items.create(session, board_id=b, kind="image", origin="upload", x=1, y=2, w=3, h=4, z=5)
    session.commit()
    session.expire_all()
    got = items.get(session, it.id)
    assert got is not None and (got.x, got.y, got.w, got.h, got.z) == (1, 2, 3, 4, 5)
    items.update_position(session, it.id, 10.5, 20.5, 30, 40, 7)
    session.commit()
    session.expire_all()
    got = items.get(session, it.id)
    assert got is not None and (got.x, got.y, got.w, got.h, got.z) == (10.5, 20.5, 30, 40, 7)


def test_item_with_parent_item_id_links_to_parent(session: Session) -> None:
    b = _board(session)
    parent = items.create(session, board_id=b, kind="image", origin="upload", sha256="p")
    child = items.create(
        session, board_id=b, kind="image", origin="candidate", sha256="c", parent_item_id=parent.id
    )
    assert child.parent_item_id == parent.id
    assert [c.id for c in items.children(session, parent.id)] == [child.id]
    with pytest.raises(IntegrityError), session.begin_nested():
        items.create(session, board_id=b, kind="image", origin="seed", parent_item_id="itm_x")


def test_licensed_item_requires_corpus_item_id_user_supplied_must_not_have_one(
    session: Session,
) -> None:
    b = _board(session)
    cx = corpus.create(
        session, domain="d", source="s", source_id="1", landing_url="u", image_url="i",
        license_code="cc0", attribution_text="a",
    )  # fmt: skip
    with pytest.raises(IntegrityError), session.begin_nested():
        items.create(session, board_id=b, kind="image", origin="candidate",
                     rights_status="licensed")  # fmt: skip
    with pytest.raises(IntegrityError), session.begin_nested():
        items.create(session, board_id=b, kind="image", origin="candidate",
                     rights_status="user_supplied", corpus_item_id=cx.id)  # fmt: skip
    ok = items.create(session, board_id=b, kind="image", origin="candidate",
                      rights_status="licensed", corpus_item_id=cx.id)  # fmt: skip
    assert ok.corpus_item_id == cx.id


def test_lens_versions_immutable_saving_an_edit_creates_version_2(session: Session) -> None:
    b = _board(session)
    v1 = lenses.save(session, board_id=b, domain="d", origin="curated", spec={"a": 1})
    v2 = lenses.save(session, board_id=b, domain="d", origin="user", spec={"a": 2})
    assert (v1.version, v2.version) == (1, 2) and v1.id != v2.id
    session.commit()
    session.expire_all()
    got1 = lenses.get(session, v1.id)
    assert got1 is not None and got1.spec_json == {"a": 1}
    assert lenses.latest(session, b, "d").id == v2.id  # type: ignore[union-attr]
    other = lenses.save(session, board_id=None, domain="d", origin="curated", spec={})
    assert other.version == 1


def test_append_only_repos_expose_no_update_or_delete() -> None:
    for mod in (decisions, attributes):
        names = [n for n, f in inspect.getmembers(mod, inspect.isfunction)
                 if f.__module__ == mod.__name__ and not n.startswith("_")]  # fmt: skip
        assert names
        assert not [n for n in names if n.startswith(("update", "delete", "remove", "set_"))]


def test_attribute_events_append_and_list(session: Session) -> None:
    b = _board(session)
    it = items.create(session, board_id=b, kind="image", origin="upload")
    attributes.append_event(
        session, item_id=it.id, key="k", actor="model", action="extracted",
        before_json=None, after_json={"v": 1},
    )  # fmt: skip
    attributes.append_event(
        session, item_id=it.id, key="k", actor="user", action="edited",
        before_json={"v": 1}, after_json={"v": 2},
    )  # fmt: skip
    assert [e.action for e in attributes.events(session, it.id, "k")] == ["extracted", "edited"]


def test_decision_history_newest_first(session: Session) -> None:
    b = _board(session)
    for d in ("reject", "keep", "reject"):
        decisions.append(
            session, board_id=b, run_id="run_1", run_candidate_id="cand_1",
            corpus_item_id="cx_1", decision=d,
        )  # fmt: skip
    session.expire_all()
    hist = decisions.history(session, "cand_1")
    assert [h.decision for h in hist] == ["reject", "keep", "reject"]
    assert [h.id for h in hist] == sorted((h.id for h in hist), reverse=True)
    assert decisions.history(session, "cand_other") == []


def test_board_profiles_keeps_history_latest_returns_highest_version(session: Session) -> None:
    b = _board(session)
    assert profiles.latest(session, b) is None
    assert profiles.save(session, b, {"n": 1}) == 1
    assert profiles.save(session, b, {"n": 2}) == 2
    latest = profiles.latest(session, b)
    assert latest is not None and latest.version == 2 and latest.profile_json == {"n": 2}
    assert [p.version for p in profiles.history(session, b)] == [2, 1]
