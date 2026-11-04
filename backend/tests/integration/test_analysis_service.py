from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.analysis import service
from app.analysis.analysers import Hints, ItemContent, build_prompt
from app.analysis.context import hints_for
from app.analysis.types import Analysis, DimensionOut, PartOut
from app.api import deps
from app.board import profile_hook
from app.db.models import BoardItem, Exploration, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.errors import AppError
from app.providers.reliability import ModelError
from app.storage import files
from tests.media import image_bytes


@pytest.fixture(autouse=True)
def env(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)
    saved = dict(jobs._registry)
    yield
    jobs._registry.clear()
    jobs._registry.update(saved)


def add_image(session: Session, board_id: str, shade: int = 0, **fields: Any) -> BoardItem:
    data = image_bytes(seed=shade)
    sha = files.sha256_hex(data)
    item = items_repo.create(
        session, board_id=board_id, kind="image", origin="upload", sha256=sha,
        storage_path=files.save_original(data, sha, "png"), **fields,
    )  # fmt: skip
    session.commit()
    return item


def rows(session: Session, item_id: str) -> dict[str, ItemAttribute]:
    session.expire_all()
    return {a.key: a for a in attrs_repo.for_item(session, item_id)}


def parts(session: Session, item_id: str) -> dict[str, ItemPart]:
    session.expire_all()
    return {p.key: p for p in session.scalars(select(ItemPart).where(ItemPart.item_id == item_id))}


def dim(key: str, **kw: Any) -> DimensionOut:
    base: dict[str, Any] = {
        "key": key, "label": key.title(), "type": "abstract", "part": None,
        "prompt": f"What is the {key}?", "kind": "text", "value": "x", "confidence": 0.9,
    }  # fmt: skip
    return DimensionOut(**{**base, **kw})


def test_upload_runs_analyse_and_stores_parts(client: TestClient) -> None:
    board = client.post("/api/boards", json={"title": "B"}).json()["id"]
    r = client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", ("a.png", image_bytes(), "application/octet-stream"))],
    )
    item_id = r.json()["results"][0]["item"]["id"]
    with deps._factory()() as s:
        item = items_repo.get(s, item_id)
        assert item is not None
        assert (item.parse_status, item.content_type) == ("completed", "image")
        got = rows(s, item_id)
        assert any(a.dim_type == "abstract" for a in got.values())
        assert got["body_colour"].dim_type == "physical" and got["body_colour"].spec_json
        assert got["subject"].source == "model" and got["subject"].prompt
    view = client.get(f"/api/items/{item_id}/analysis").json()
    assert {p["key"] for p in view["parts"]} == {"body", "detail"}


def test_rerun_keeps_you_rows_and_respects_removed(session: Session) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    got = rows(session, item.id)
    assert "detail_style" in got and "subject" in got

    got["subject"].value_json = "my words"
    got["subject"].source = "you"
    got["detail_style"].removed = True
    p = parts(session, item.id)
    p["body"].source = "you"
    p["body"].label = "My body"
    p["detail"].removed = True
    session.commit()

    service.analyse(session, item.id)
    got = rows(session, item.id)
    assert (got["subject"].value_json, got["subject"].source) == ("my words", "you")
    assert got["detail_style"].removed is True  # still there, still removed, never refreshed
    p = parts(session, item.id)
    assert (p["body"].source, p["body"].label) == ("you", "My body")
    assert p["detail"].removed is True
    assert items_repo.get(session, item.id).parse_status == "completed"  # type: ignore[union-attr]


def test_removed_row_is_never_re_added_with_new_value(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    rows(session, item.id)["subject"].removed = True
    session.commit()
    answer = Analysis(
        content_type="image", summary="", parts=[], dimensions=[dim("subject", value="NEW")]
    )
    monkeypatch.setattr(service, "run_analyser", lambda *_a: answer)
    service.analyse(session, item.id)
    row = rows(session, item.id)["subject"]
    assert row.removed is True and row.value_json == "an object"


def test_ai_row_with_exploration_goes_stale_not_deleted(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    session.add(Exploration(board_id=board.id, item_id=item.id, key="medium"))
    session.commit()
    answer = Analysis(
        content_type="image", summary="", parts=[], dimensions=[dim("subject", value="s")]
    )
    monkeypatch.setattr(service, "run_analyser", lambda *_a: answer)
    service.analyse(session, item.id)
    got = rows(session, item.id)
    assert set(got) == {"subject", "medium"}  # body_colour etc. deleted, explored one kept
    assert got["medium"].status == "stale"
    assert got["subject"].value_json == "s" and got["subject"].status == "extracted"


def test_blank_item_completes_with_no_parts(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    blank = Analysis(content_type="image", summary="", parts=[], dimensions=[])
    monkeypatch.setattr(service, "run_analyser", lambda *_a: blank)
    assert service.analyse(session, item.id) == blank
    session.expire_all()
    got = items_repo.get(session, item.id)
    assert got is not None and got.parse_status == "completed" and got.parse_error_code is None
    assert parts(session, item.id) == {} and rows(session, item.id) == {}


def test_model_failure_marks_item_failed_without_raising(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)

    def boom(*_a: object) -> Analysis:
        raise ModelError("MODEL_TIMEOUT", message="slow")

    monkeypatch.setattr(service, "run_analyser", boom)
    assert service.analyse(session, item.id) is None
    session.expire_all()
    got = items_repo.get(session, item.id)
    assert got is not None and (got.parse_status, got.parse_error_code) == (
        "failed", "MODEL_TIMEOUT",
    )  # fmt: skip


def test_analyse_while_processing_is_409(session: Session) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id, parse_status="processing")
    with pytest.raises(AppError) as e:
        service.analyse(session, item.id)
    assert e.value.status == 409


def test_edit_during_analysis_survives_merge(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    real = service.run_analyser

    def edit_then_answer(*a: Any) -> Analysis:
        other = Session(session.get_bind())
        row = other.scalars(
            select(ItemAttribute).where(
                ItemAttribute.item_id == item.id, ItemAttribute.key == "subject"
            )
        ).one()
        row.value_json, row.source = "mine", "you"
        other.commit()
        other.close()
        return real(*a)

    monkeypatch.setattr(service, "run_analyser", edit_then_answer)
    service.analyse(session, item.id)
    assert rows(session, item.id)["subject"].value_json == "mine"


def test_note_creation_enqueues_analyse(client: TestClient) -> None:
    seen: list[str] = []
    jobs.register("analyse_item", lambda item_id: seen.append(item_id))
    board = client.post("/api/boards", json={"title": "B"}).json()["id"]
    r = client.post(f"/api/boards/{board}/notes", json={"text": "warm and quiet", "x": 1, "y": 2})
    assert r.status_code == 201
    assert seen == [r.json()["id"]]
    seen.clear()
    # still queued (the stub never ran it): the queued job reads the new text, no second job
    r2 = client.patch(f"/api/items/{r.json()['id']}", json={"note_text": "cold and loud"})
    assert r2.status_code == 200 and seen == []
    with deps._factory()() as s:
        s.get(BoardItem, r.json()["id"]).parse_status = "completed"  # type: ignore[union-attr]
        s.commit()
    r3 = client.patch(f"/api/items/{r.json()['id']}", json={"note_text": "cold and still"})
    assert r3.status_code == 200 and seen == [r.json()["id"]]


def test_note_is_analysed_into_text_parts(client: TestClient) -> None:
    board = client.post("/api/boards", json={"title": "B"}).json()["id"]
    note_id = client.post(
        f"/api/boards/{board}/notes", json={"text": "warm and quiet", "x": 1, "y": 2}
    ).json()["id"]
    with deps._factory()() as s:
        item = items_repo.get(s, note_id)
        assert item is not None and (item.parse_status, item.content_type) == ("completed", "text")
        assert {p.region_kind for p in parts(s, note_id).values()} == {"text_range"}
        assert {"tone", "length"} <= set(rows(s, note_id))


def test_hints_carry_you_removed_and_parent_dimensions(session: Session) -> None:
    board = boards_repo.create(session, "B")
    parent = add_image(session, board.id)
    service.analyse(session, parent.id)
    rows(session, parent.id)["medium"].removed = True
    child = add_image(session, board.id, shade=1, parent_item_id=parent.id)
    attrs_repo.upsert(
        session, child.id, "mood", label="Mood", category="abstract", kind="text",
        confidence=1.0, status="edited", source="you",
    )  # fmt: skip
    attrs_repo.upsert(
        session, child.id, "grain", label="Grain", category="abstract", kind="text",
        confidence=1.0, status="edited", source="model", removed=True,
    )  # fmt: skip
    session.add(ItemPart(item_id=child.id, key="sky", label="Sky", region_kind="mask",
                         source="you"))  # fmt: skip
    session.commit()
    hints = hints_for(session, board.id, child.id)
    assert hints.you_dimensions == ["mood"] and hints.you_parts == ["sky"]
    assert hints.removed == ["grain"]
    keys = {d["key"] for d in hints.parent_dimensions}
    assert "subject" in keys and "medium" not in keys
    subject = next(d for d in hints.parent_dimensions if d["key"] == "subject")
    assert subject == {
        "key": "subject", "label": "Subject", "type": "abstract", "part": None, "kind": "text",
    }  # fmt: skip
    prompt = build_prompt(ItemContent("c", "image", image=b"x"), "", hints)
    assert "derived from another item" in prompt and "subject (Subject, abstract, text)" in prompt
    assert "derived" not in build_prompt(ItemContent("c", "image", image=b"x"), "", Hints.empty())


def test_part_dropped_by_new_analysis_is_deleted_unless_a_dimension_uses_it(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    rows(session, item.id)["detail_style"].source = "you"
    session.commit()
    only_body = Analysis(
        content_type="image", summary="",
        parts=[PartOut(key="body", label="Body", region_kind="mask")], dimensions=[],
    )  # fmt: skip
    monkeypatch.setattr(service, "run_analyser", lambda *_a: only_body)
    service.analyse(session, item.id)
    assert set(parts(session, item.id)) == {"body", "detail"}  # "detail" carries a you row


def test_recover_stuck_analyses_requeues_pending_and_processing(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    stuck = [
        add_image(session, board.id, shade=1, parse_status="pending"),
        add_image(session, board.id, shade=2, parse_status="processing"),
    ]
    untouched = {
        s: add_image(session, board.id, shade=i + 3, parse_status=s)
        for i, s in enumerate(("failed", "completed", "pending_lens"))
    }
    gone = add_image(session, board.id, shade=9, parse_status="pending")
    gone.removed_at = "2026-11-01T00:00:00+00:00"
    session.commit()
    queued: list[str] = []
    monkeypatch.setattr(service.jobs, "enqueue", lambda name, **kw: queued.append(kw["item_id"]))

    assert service.recover_stuck_analyses(session) == 2
    session.commit()

    assert sorted(queued) == sorted(i.id for i in stuck)
    for item in stuck:
        session.refresh(item)
        assert item.parse_status == "pending"  # claimable again
    for status, item in untouched.items():
        session.refresh(item)
        assert item.parse_status == status
    session.refresh(gone)
    assert gone.parse_status == "pending" and gone.id not in queued


def test_recover_stuck_analyses_skips_models(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    model = add_image(session, board.id, shade=1, parse_status="pending")
    model.kind = "model"
    session.commit()
    queued: list[str] = []
    monkeypatch.setattr(service.jobs, "enqueue", lambda name, **kw: queued.append(kw["item_id"]))
    assert service.recover_stuck_analyses(session) == 0
    assert queued == []
    session.refresh(model)
    assert model.parse_status == "pending"


def test_recovered_processing_item_gets_analysed(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id, parse_status="processing")
    monkeypatch.setattr(service, "run_analyser", lambda *_a: blank)
    blank = Analysis(content_type="image", summary="", parts=[], dimensions=[])
    queued: list[str] = []
    monkeypatch.setattr(service.jobs, "enqueue", lambda name, **kw: queued.append(kw["item_id"]))
    service.recover_stuck_analyses(session)
    session.commit()
    assert queued == [item.id]
    service.analyse(session, item.id)
    session.refresh(item)
    assert item.parse_status == "completed"


def test_startup_recovery_calls_recover_stuck_analyses(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main

    calls: list[object] = []
    monkeypatch.setattr(deps, "new_session", lambda: session)
    monkeypatch.setattr(service, "recover_stuck_analyses", lambda s: calls.append(s) or 0)
    monkeypatch.setattr(session, "close", lambda: None)
    main._recover_visualizing()
    assert len(calls) == 1


def test_analysis_subject_is_stored_and_overwritten(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = boards_repo.create(session, "B")
    item = add_image(session, board.id)
    service.analyse(session, item.id)
    assert items_repo.get(session, item.id).subject == "main object"  # type: ignore[union-attr]
    answer = Analysis(
        content_type="image", summary="", subject="running shoe", parts=[], dimensions=[]
    )
    monkeypatch.setattr(service, "run_analyser", lambda *_a: answer)
    service.analyse(session, item.id)
    session.expire_all()
    assert items_repo.get(session, item.id).subject == "running shoe"  # type: ignore[union-attr]
