"""Render view: the same design drawn again from another viewpoint, added as a child."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import demo, events, jobs
from app.analysis import extract
from app.db.models import BoardItem
from app.providers.reasoning import MockReasoningProvider
from app.providers.reliability import ModelError
from app.views import service
from app.views.service import view_prompt

PASSCODE = "open sesame"


def anchor_of(world: dict[str, Any]) -> str:
    return world["items"][world["watch"]][0]  # type: ignore[no-any-return]


def post(client: TestClient, item: str, **body: Any) -> Any:
    return client.post(f"/api/items/{item}/render-view", json=body)


def renders(world: dict[str, Any]) -> int:
    return len(demo.windows._hits.get(f"render:{world['watch']}", ()))


def children(world: dict[str, Any], anchor: str) -> list[BoardItem]:
    s = world["session"]
    s.expire_all()
    q = select(BoardItem).where(BoardItem.parent_item_id == anchor, BoardItem.origin == "generated")
    return list(s.scalars(q))


def collect(sub: Any) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    while (ev := sub.get(timeout=0.5)) is not None:
        seen.append(ev)
    return seen


def test_render_view_adds_a_child_of_the_anchor(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    r = post(client, anchor, view="from the rear right")
    assert r.status_code == 202, r.json()
    got = r.json()
    assert set(got) == {"job_id", "x", "y", "w", "h"} and got["job_id"].startswith("view_")
    (item,) = children(world, anchor)
    assert item.kind == "image" and item.rights_status == "generated" and item.staged is False
    assert (item.x, item.y, item.w, item.h) == (got["x"], got["y"], got["w"], got["h"])
    gen = item.generation_json
    assert gen["view"] == "from the rear right" and gen["view_job"] == got["job_id"]
    assert gen["model"] == "mock-image" and "from the rear right" in gen["prompt"]
    assert item.original_filename is not None
    assert item.original_filename.endswith(", from the rear right.png")
    listed = client.get(f"/api/boards/{world['watch']}/items").json()
    listed = listed["items"] if isinstance(listed, dict) else listed
    made = next(i for i in listed if i["id"] == item.id)
    assert made["parent_item_id"] == anchor and made["origin"] == "generated"
    assert made["generation"]["view_job"] == got["job_id"]
    assert renders(world) == 1


def test_render_view_publishes_added_then_done(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    with events.subscribe(world["watch"]) as sub:
        job = post(client, anchor, view="from the front left").json()["job_id"]
        seen = collect(sub)
    (item,) = children(world, anchor)
    types = [e["type"] for e in seen if e["type"] in ("item.added", "view.done", "view.failed")]
    assert types == ["item.added", "view.done"]
    done = next(e for e in seen if e["type"] == "view.done")
    assert done["data"] == {"job_id": job, "item_id": item.id, "check": item.check_json}


def test_view_prompt_keeps_the_design_and_adds_words() -> None:
    p = view_prompt("seen from inside, from the open door", "plain studio background")
    assert "seen from inside, from the open door" in p
    assert "same shape, proportions, colours, materials and details" in p
    assert p.endswith("plain studio background.")
    assert not view_prompt("from above", None).endswith(" .")
    assert view_prompt("from above", "  ") == view_prompt("from above", None)


def test_view_refuses_note_and_costs_no_render(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    note = client.post(f"/api/boards/{world['watch']}/notes", json={"text": "hi", "x": 0, "y": 0})
    r = post(client, note.json()["id"], view="from above")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VIEW_NOT_IMAGE"
    assert renders(world) == 0


def test_view_refuses_staged_and_unknown(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    s = world["session"]
    s.get(BoardItem, anchor).staged = True
    s.commit()
    r = post(client, anchor, view="from above")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VIEW_NOT_IMAGE"
    r = post(client, "item_missing", view="from above")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ITEM_NOT_FOUND"
    assert renders(world) == 0


def test_view_rejects_empty_and_long_view(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    for bad in (
        post(client, anchor, view="  "),
        post(client, anchor, view="x" * 121),
        post(client, anchor, view="from above", words="x" * 201),
    ):  # the app answers body validation with 400 VALIDATION_ERROR
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert children(world, anchor) == [] and renders(world) == 0


def test_view_is_stripped(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    assert post(client, anchor, view="  from above ").status_code == 202
    (item,) = children(world, anchor)
    assert item.generation_json["view"] == "from above"


def test_view_of_removed_anchor_fails_and_refunds(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append({"name": name, **kw}))
    anchor = anchor_of(world)
    assert post(client, anchor, view="from above").status_code == 202
    (job,) = queued
    assert job.pop("name") == service.JOB
    assert renders(world) == 1  # counted by the request
    assert client.delete(f"/api/items/{anchor}").status_code == 204
    with events.subscribe(world["watch"]) as sub:
        service.render_view_job(**job)
        seen = collect(sub)
    failed = [e for e in seen if e["type"] == "view.failed"]
    assert [e["data"]["code"] for e in failed] == ["ITEM_NOT_FOUND"]
    assert failed[0]["data"]["job_id"] == job["job_id"]
    assert not [e for e in seen if e["type"] in ("item.added", "view.done")]
    assert children(world, anchor) == [] and renders(world) == 0  # refunded


class Timeout:
    id = "timeout"
    model = "timeout-image"
    is_mock = True

    def edit(self, image: bytes, prompt: str) -> bytes:
        raise ModelError("MODEL_TIMEOUT", message="slow")


def test_model_failure_refunds_and_reports(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(service, "get_image_provider", lambda _s: Timeout())
    anchor = anchor_of(world)
    with events.subscribe(world["watch"]) as sub:
        r = post(client, anchor, view="from above")
        seen = collect(sub)
    assert r.status_code == 202
    failed = [e for e in seen if e["type"] == "view.failed"]
    assert len(failed) == 1 and failed[0]["data"]["code"] == "MODEL_TIMEOUT"
    assert failed[0]["data"]["job_id"] == r.json()["job_id"]
    assert children(world, anchor) == [] and renders(world) == 0


def test_unexpected_error_refunds_and_reports(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_stamped", boom)
    anchor = anchor_of(world)
    with events.subscribe(world["watch"]) as sub:
        assert post(client, anchor, view="from above").status_code == 202
        seen = collect(sub)
    failed = [e for e in seen if e["type"] == "view.failed"]
    assert len(failed) == 1 and failed[0]["data"]["code"] == "VIEW_ERROR"
    assert failed[0]["data"]["message"] == "Could not make this view"
    assert renders(world) == 0


def test_two_views_each_get_their_own_slot(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    a = post(client, anchor, view="from above").json()
    b = post(client, anchor, view="from below").json()
    assert a["job_id"] != b["job_id"] and (a["x"], a["y"]) != (b["x"], b["y"])
    assert len(children(world, anchor)) == 2


def test_view_is_demo_locked(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", PASSCODE)
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)
    r = post(client, anchor, view="from above")
    assert r.status_code == 403 and r.json()["error"]["code"] == "DEMO_LOCKED"
    assert children(world, anchor) == []


def held(world: dict[str, Any]) -> dict[str, Any]:
    return extract._reserved.get(world["watch"], {})


def test_queued_views_reserve_their_slots_until_the_job_ends(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append(kw))
    anchor = anchor_of(world)
    a = post(client, anchor, view="from above").json()
    b = post(client, anchor, view="from below").json()  # the first picture does not exist yet
    assert (a["x"], a["y"]) != (b["x"], b["y"]) and len(held(world)) == 2
    service.render_view_job(**queued[0])  # success releases
    assert set(held(world)) == {queued[1]["job_id"]}
    assert len(children(world, anchor)) == 1
    monkeypatch.setattr(service, "get_image_provider", lambda _s: Timeout())
    service.render_view_job(**queued[1])  # a model failure releases
    assert held(world) == {}


def test_unexpected_failure_and_refusal_leave_no_reservation(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    assert post(client, anchor, view="").status_code == 400
    assert held(world) == {}  # a refused request reserves nothing

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_stamped", boom)
    assert post(client, anchor, view="from above").status_code == 202
    assert held(world) == {}  # the catch-all wrapper released it


def test_a_failed_request_releases_its_reservation(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    service.request_render_view(s, anchor_of(world), "from above", None)
    assert len(held(world)) == 1
    s.rollback()  # the request's transaction did not commit
    assert held(world) == {}


def test_a_queue_failure_releases_its_reservation(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(name: str, **kw: Any) -> None:
        raise RuntimeError("no pool")

    monkeypatch.setattr(jobs, "enqueue", boom)
    post(client, anchor_of(world), view="from above")
    assert held(world) == {}


def test_a_view_is_read_like_any_new_picture(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    anchor = anchor_of(world)
    assert post(client, anchor, view="from above").status_code == 202
    (item,) = children(world, anchor)
    assert item.parse_status == "completed"  # queued for analysis, not left pending forever


def test_startup_recovery_leaves_views_alone(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    from app.api import deps
    from app.explore.visualize import recover_stuck

    anchor = anchor_of(world)
    assert post(client, anchor, view="from above").status_code == 202
    s = deps._factory()()
    try:
        recover_stuck(s)
        s.commit()
    finally:
        s.close()
    (item,) = children(world, anchor)
    assert item.check_json is not None  # its check ran in the job; recovery leaves it alone
    item.generation_json = {**item.generation_json, "checking": True}  # a check cut off
    world["session"].commit()
    s = deps._factory()()
    try:
        recover_stuck(s)
        s.commit()
    finally:
        s.close()
    (item,) = children(world, anchor)
    assert "checking" not in item.generation_json  # no longer waited on; the check is kept
    assert item.check_json is not None


def test_view_result_has_check(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    asked: list[str] = []

    def no(_self: Any, _images: list[bytes], prompt: str) -> dict[str, Any]:
        asked.append(prompt)
        return {"answer": "no", "confidence": 0.7, "box": None, "note": "other design"}

    monkeypatch.setattr(MockReasoningProvider, "check_target", no)
    anchor = anchor_of(world)
    assert post(client, anchor, view="from above").status_code == 202
    (item,) = children(world, anchor)
    assert item.check_json == {"target_ok": False, "answer": "no"}
    assert "the same design seen from from above" in asked[0]


def test_view_check_failure_leaves_the_result_unchecked(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    def down(*_a: Any, **_k: Any) -> Any:
        raise ModelError("MODEL_TIMEOUT", message="slow")

    monkeypatch.setattr(MockReasoningProvider, "check_target", down)
    anchor = anchor_of(world)
    assert post(client, anchor, view="from above").status_code == 202
    (item,) = children(world, anchor)
    assert item.check_json is None and renders(world) == 1


@pytest.mark.file_db
def test_view_is_committed_before_its_check(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import deps

    anchor = anchor_of(world)
    during: list[list[tuple[str, Any]]] = []

    def look(_self: Any, _images: list[bytes], _prompt: str) -> dict[str, Any]:
        with deps._factory()() as s:
            s.execute(text("PRAGMA busy_timeout=200"))
            q = select(BoardItem).where(
                BoardItem.parent_item_id == anchor, BoardItem.origin == "generated"
            )
            during.append([(m.id, (m.generation_json or {}).get("checking")) for m in s.scalars(q)])
            row = s.get(BoardItem, anchor)
            assert row is not None
            row.x += 1  # another writer is not kept waiting
            s.commit()
        return {"answer": "yes", "confidence": 0.9, "box": None, "note": ""}

    monkeypatch.setattr(MockReasoningProvider, "check_target", look)
    with events.subscribe(world["watch"]) as sub:
        assert post(client, anchor, view="from above").status_code == 202
        seen = collect(sub)
    (item,) = children(world, anchor)
    assert during == [[(item.id, True)]]
    assert "checking" not in item.generation_json and item.check_json["answer"] == "yes"
    done = next(e for e in seen if e["type"] == "view.done")
    assert done["data"]["check"] == item.check_json
    types = [e["type"] for e in seen if e["type"] in ("item.added", "item.updated", "view.done")]
    assert types[:3] == ["item.added", "item.updated", "view.done"]
