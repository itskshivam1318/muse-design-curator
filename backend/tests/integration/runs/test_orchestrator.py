from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app import events
from app.db.models import BoardItem, CorpusItem, VariationRun
from app.db.repos import attributes as attrs_repo
from app.db.repos import runs as runs_repo
from app.domain.variation import VariationRequest
from app.errors import AppError
from app.providers.reliability import ModelError
from app.runs import orchestrator


def source_with(world: dict[str, Any], board: str, *keys: str) -> str:
    s = world["session"]
    s.expire_all()
    for iid in world["items"][board]:
        have = {r.key for r in attrs_repo.for_item(s, iid) if r.value_json is not None}
        if set(keys) <= have:
            return iid
    raise AssertionError(f"no item with {keys}")


def make_run(world: dict[str, Any], board: str, **over: Any) -> VariationRun:
    s = world["session"]
    req = VariationRequest(
        **{"source_item_id": source_with(world, board, "dial_color"), "target_key": "dial_color",
           "mode": "explore", **over}
    )  # fmt: skip
    run = orchestrator.create_run(s, board, req, over.pop("key", None))
    s.commit()
    s.expire_all()
    return s.get(VariationRun, run.id)  # type: ignore[return-value]


def cands(world: dict[str, Any], run: VariationRun):  # type: ignore[no-untyped-def]
    return runs_repo.candidates(world["session"], run.id)


def colour_of(world: dict[str, Any], corpus_id: str) -> Any:
    from app.db.repos import corpus as corpus_repo

    return next(a.value_json for a in corpus_repo.attributes(world["session"], corpus_id)
                if a.key == "dial_color")  # fmt: skip


def test_explore_colour_returns_distinct_validated_colours_not_source(world) -> None:  # type: ignore[no-untyped-def]
    run = make_run(world, world["watch"])
    assert run.status == "completed", run.error_code
    s = world["session"]
    src = {r.key: r.value_json for r in attrs_repo.for_item(s, run.source_item_id)}["dial_color"]
    ranked = [c for c in cands(world, run) if c.rank is not None]
    assert 0 < len(ranked) <= 6
    assert all(c.state == "validated" for c in ranked)
    colours = [colour_of(world, c.corpus_item_id) for c in ranked]
    # diversity is a soft score (not a hard rule): the eight-image fixture corpus can repeat a name
    assert all(c != src for c in colours) and len(set(colours)) >= len(colours) - 1
    assert [c.rank for c in ranked] == list(range(1, len(ranked) + 1))
    assert run.summary_json["returned"] == len(ranked)


def test_fewer_than_six_returns_shortfall_reasons(world) -> None:  # type: ignore[no-untyped-def]
    run = make_run(world, world["watch"], protected_keys=["strap_color"])
    assert run.status == "completed", run.error_code
    summ = run.summary_json
    assert summ["returned"] < 6 and summ["shortfall"]
    for row in summ["shortfall"]:
        assert set(row) == {"code", "count", "message"} and row["count"] > 0
    prot = [r for r in summ["shortfall"] if r["code"] == "protected_changed"]
    assert prot and prot[0]["message"].endswith("changed a protected attribute (Strap colour)")
    again = orchestrator.summarize_run(world["session"], run, _lens(world, run))
    assert again == summ  # deterministic


def _lens(world: dict[str, Any], run: VariationRun):  # type: ignore[no-untyped-def]
    from app.db.repos import lenses as lenses_repo
    from app.domain.lens import LensSpec

    return LensSpec.model_validate(lenses_repo.get(world["session"], run.lens_id).spec_json)  # type: ignore[union-attr]


def test_never_returns_source_or_duplicate(world) -> None:  # type: ignore[no-untyped-def]
    from app.corpus.hashing import hamming

    run = make_run(world, world["watch"])
    s = world["session"]
    src = s.get(BoardItem, run.source_item_id)
    items = [s.get(CorpusItem, c.corpus_item_id) for c in cands(world, run) if c.rank]
    assert all(i.id != src.corpus_item_id and i.sha256 != src.sha256 for i in items)
    for n, a in enumerate(items):
        for b in items[n + 1 :]:
            assert a.sha256 != b.sha256 and hamming(a.dhash, b.dhash) > 6


def test_uncertain_only_in_needs_review(world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run = make_run(world, world["watch"], protected_keys=["case_shape"])
    assert run.status == "completed"
    rows = cands(world, run)
    ranked = {c.id for c in rows if c.rank is not None}
    uncertain = {c.id for c in rows if c.state == "uncertain"}
    assert not ranked & uncertain
    assert all(c.state == "validated" for c in rows if c.id in ranked)


def test_run_stores_versions_and_snapshot(world) -> None:  # type: ignore[no-untyped-def]
    run = make_run(world, world["watch"])
    assert run.ranking_version == "rank-2026.10-c" and run.validator_version == "val-3"
    assert run.board_profile_version >= 1
    assert run.ranking_config_json["weights"]["target"] == 0.35
    assert run.providers_json["reasoning"]["is_mock"] is True
    assert run.providers_json["segmentation"] == {"id": "mock", "is_mock": True}
    assert run.providers_json["embedder"] == {"id": "mock"}
    snap = {r["key"]: r for r in run.source_snapshot_json}
    assert snap["dial_color"]["measured"]["lab"], "measured data must be in the snapshot"
    assert run.lens_id and run.status == "completed" and run.completed_at


def test_same_key_same_run_no_duplicate_rows(world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    req = VariationRequest(
        source_item_id=source_with(world, world["watch"], "dial_color"),
        target_key="dial_color", mode="explore",
    )  # fmt: skip
    a = orchestrator.create_run(s, world["watch"], req, "k1")
    s.commit()
    n = s.scalar(select(func.count()).select_from(runs_repo.RunCandidate))  # type: ignore[attr-defined]
    b = orchestrator.create_run(s, world["watch"], req, "k1")
    s.commit()
    assert a.id == b.id
    assert s.scalar(select(func.count()).select_from(VariationRun)) == 1
    assert s.scalar(select(func.count()).select_from(runs_repo.RunCandidate)) == n  # type: ignore[attr-defined]
    other = req.model_copy(update={"mode": "avoid", "target_values": ["red"]})
    with pytest.raises(AppError) as e:
        orchestrator.create_run(s, world["watch"], other, "k1")
    assert e.value.status == 409 and e.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_422_creates_no_run(world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    req = VariationRequest(
        source_item_id=source_with(world, world["watch"], "dial_color"),
        target_key="nope", mode="explore",
    )  # fmt: skip
    with pytest.raises(AppError) as e:
        orchestrator.create_run(s, world["watch"], req, "k2")
    assert e.value.status == 422
    s.rollback()
    assert s.scalar(select(func.count()).select_from(VariationRun)) == 0


def test_lens_and_source_readiness_409(world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    from app.db.models import Board

    iid = source_with(world, world["watch"], "dial_color")
    req = VariationRequest(source_item_id=iid, target_key="dial_color", mode="explore")
    item = s.get(BoardItem, iid)
    saved, item.embedding_json = item.embedding_json, None
    with pytest.raises(AppError) as e:
        orchestrator.create_run(s, world["watch"], req, None)
    assert (e.value.status, e.value.code) == (409, "SOURCE_NOT_READY")
    item.embedding_json = saved
    board = s.get(Board, world["watch"])
    lens_id, board.lens_id = board.lens_id, None
    with pytest.raises(AppError) as e:
        orchestrator.create_run(s, world["watch"], req, None)
    assert (e.value.status, e.value.code) == (409, "LENS_REQUIRED")
    board.lens_id = lens_id
    s.rollback()
    assert s.scalar(select(func.count()).select_from(VariationRun)) == 0


def test_provider_timeout_during_verify_is_uncertain_and_run_completes(
    world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    class Down:
        id, model, is_mock = "down", "m", False

        def verify(self, *a: Any, **k: Any) -> Any:
            raise ModelError("TIMEOUT")

    monkeypatch.setattr(orchestrator, "get_reasoning", lambda _s: Down())
    run = make_run(
        world, world["watch"], protected_keys=["case_shape"],
        source_item_id=source_with(world, world["watch"], "dial_color", "case_shape"),
    )  # fmt: skip
    assert run.status == "completed", run.error_code
    unc = [c for c in cands(world, run) if c.state == "uncertain"]
    assert unc
    reasons = [v.reason for c in unc for v in runs_repo.validations(world["session"], c.id)]
    assert any("TIMEOUT" in r for r in reasons)
    assert all(c.rank is None for c in unc)


def test_fashion_board_never_returns_watch_items(world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    s.expire_all()
    iid = next(
        i for i in world["items"][world["fashion"]]
        if any(r.key == "primary_color" and r.value_json for r in attrs_repo.for_item(s, i))
    )  # fmt: skip
    req = VariationRequest(source_item_id=iid, target_key="primary_color", mode="explore")
    run = orchestrator.create_run(s, world["fashion"], req, None)
    s.commit()
    s.expire_all()
    run = s.get(VariationRun, run.id)
    assert run.status == "completed", run.error_code
    rows = cands(world, run)
    assert rows
    assert {s.get(CorpusItem, c.corpus_item_id).domain for c in rows} == {"fashion"}


def test_progress_events_in_stage_order(world) -> None:  # type: ignore[no-untyped-def]
    with events.subscribe(world["watch"]) as sub:
        run = make_run(world, world["watch"])
        got = []
        while (ev := sub.get(timeout=0.2)) is not None:
            if ev["type"] == "run.progress":
                got.append(ev["data"])
    assert all(d["run_id"] == run.id for d in got)
    stages = [d["stage"] for d in got]
    assert stages[0] == "retrieving" and stages[-1] == "completed"
    order = {"retrieving": 0, "validating": 1, "completed": 2}
    assert [order[x] for x in stages] == sorted(order[x] for x in stages)
    assert "validating" in stages
    validated = [d["validated_n"] for d in got if d["stage"] == "validating"]
    assert validated == sorted(validated)
    assert got[-1]["shortlist_n"] == run.progress_json["shortlist_n"]


def test_failure_marks_run_failed_and_keeps_rows(world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*a: Any, **k: Any) -> Any:
        raise AppError(500, "BOOM", "x")

    monkeypatch.setattr(orchestrator, "validate_shortlist", boom)
    run = make_run(world, world["watch"])
    assert run.status == "failed" and run.error_code == "BOOM"
    assert cands(world, run)  # retrieval rows stay


def test_stale_run_marked_interrupted(world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    fresh = make_run(world, world["watch"])
    fresh.status = "retrieving"
    assert not orchestrator.mark_stale(s, fresh)
    later = datetime.now(UTC) + timedelta(minutes=6)
    assert orchestrator.mark_stale(s, fresh, later)
    assert (fresh.status, fresh.error_code) == ("failed", "RUN_INTERRUPTED")
