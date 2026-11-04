"""Put into: connect one picture to another on a board to put the first into the second."""

import io
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app import demo, events, jobs
from app.analysis import extract, limits
from app.db.models import BoardItem, ItemPart
from app.providers.reliability import ModelError
from app.put import render, service
from app.put.render import point_box
from app.storage import files


def board_items(client: TestClient, world: dict[str, Any]) -> list[dict[str, Any]]:
    r = client.get(f"/api/boards/{world['watch']}/items")
    assert r.status_code == 200, r.json()
    body = r.json()
    return body["items"] if isinstance(body, dict) else body  # type: ignore[no-any-return]


def test_items_carry_put_source_item_id(client: TestClient, world: dict[str, Any]) -> None:
    items = board_items(client, world)
    assert items
    assert all(i["put_source_item_id"] is None for i in items)


# ---- the job (Task 3) ---------------------------------------------------------------------

CENTRE = [{"point": {"fx": 0.5, "fy": 0.5}}]


def two(world: dict[str, Any]) -> tuple[str, str]:
    """(target, source): two image items on the watch board."""
    a, b = world["items"][world["watch"]][:2]
    return a, b


def put(client: TestClient, target: str, source: str, spots: Any = None, words: Any = None):  # type: ignore[no-untyped-def]
    body: dict[str, Any] = {"source_id": source, "spots": CENTRE if spots is None else spots}
    if words is not None:
        body["words"] = words
    return client.post(f"/api/items/{target}/put-into", json=body)


def code(r: Any) -> str:
    return r.json()["error"]["code"]  # type: ignore[no-any-return]


def renders(world: dict[str, Any]) -> int:
    return len(demo.windows._hits.get(f"render:{world['watch']}", ()))


def results(world: dict[str, Any], target: str) -> list[BoardItem]:
    s = world["session"]
    s.expire_all()
    q = select(BoardItem).where(BoardItem.parent_item_id == target, BoardItem.origin == "generated")
    return list(s.scalars(q))


def collect(sub: Any) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    while (ev := sub.get(timeout=0.5)) is not None:
        seen.append(ev)
    return seen


def pixels(item: BoardItem) -> np.ndarray:
    assert item.storage_path is not None
    with Image.open(files.abs_path(item.storage_path)) as im:
        return np.asarray(im.convert("RGB")).astype(int)


def test_put_into_creates_a_linked_item_beside_the_target(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    with events.subscribe(world["watch"]) as sub:
        r = put(client, target, source, words="keep the blur")
        seen = collect(sub)
    assert r.status_code == 202, r.json()
    got = r.json()
    assert set(got) == {"job_id", "x", "y", "w", "h"} and got["job_id"].startswith("put_")
    (item,) = results(world, target)
    assert item.put_source_item_id == source and item.staged is False
    assert item.kind == "image" and item.rights_status == "generated"
    assert (item.x, item.y, item.w, item.h) == (got["x"], got["y"], got["w"], got["h"])
    assert item.generation_json["put_job"] == got["job_id"]
    assert item.generation_json["model"] == "mock-image"
    assert "keep the blur" in item.generation_json["prompt"]
    types = [e["type"] for e in seen if e["type"] in ("item.added", "put.done", "put.failed")]
    assert types == ["item.added", "put.done"]
    added = next(e for e in seen if e["type"] == "item.added")
    assert added["data"]["id"] == item.id and added["data"]["put_source_item_id"] == source
    done = next(e for e in seen if e["type"] == "put.done")
    assert done["data"] == {"job_id": got["job_id"], "item_id": item.id}
    assert renders(world) == 1  # a success keeps its render


def test_pixels_outside_the_spots_never_change(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    assert put(client, target, source).status_code == 202
    (item,) = results(world, target)
    t = world["session"].get(BoardItem, target)
    before, after = pixels(t), pixels(item)
    assert before.shape == after.shape
    h, w = before.shape[:2]
    x0, y0, x1, y1 = point_box((w, h), 0.5, 0.5)
    ys, xs = np.mgrid[0:h, 0:w]
    outside = (xs < x0) | (xs >= x1) | (ys < y0) | (ys >= y1)
    assert (before[outside] == after[outside]).all()
    inside = ~outside
    assert (before[inside] != after[inside]).any()  # the spot did change


def test_put_into_refuses(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    s = world["session"]
    r = put(client, target, target)
    assert r.status_code == 422 and code(r) == "PUT_NOT_IMAGE"
    note = client.post(f"/api/boards/{world['watch']}/notes", json={"text": "hi", "x": 0, "y": 0})
    r = put(client, note.json()["id"], source)
    assert r.status_code == 422 and code(r) == "PUT_NOT_IMAGE"
    staged = s.get(BoardItem, source)
    staged.staged = True
    s.commit()
    r = put(client, target, source)
    assert r.status_code == 422 and code(r) == "PUT_NOT_IMAGE"
    staged.staged = False
    s.commit()
    r = put(client, target, source, spots=[{"part": "nope"}])
    assert r.status_code == 422 and code(r) == "PART_NOT_FOUND"
    r = put(client, "item_missing", source)
    assert r.status_code == 404 and code(r) == "ITEM_NOT_FOUND"
    for bad in (
        put(client, target, source, spots=CENTRE * 9),
        put(client, target, source, spots=[]),
        put(client, target, source, spots=[{"point": {"fx": 1.5, "fy": 0.5}}]),
        put(client, target, source, words="x" * 201),
    ):  # the app answers body validation with 400 VALIDATION_ERROR
        assert bad.status_code == 400 and code(bad) == "VALIDATION_ERROR"
    assert renders(world) == 0
    assert results(world, target) == []


def test_daily_limit(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RENDER_PER_BOARD_PER_DAY", "1")
    target, source = two(world)
    limits.check_and_count(world["watch"], "render")
    r = put(client, target, source)
    assert r.status_code == 429 and code(r) == "DAILY_LIMIT"
    assert results(world, target) == []


class Timeout:
    id = "timeout"
    model = "timeout-image"
    is_mock = True

    def edit(self, image: bytes, prompt: str) -> bytes:
        raise ModelError("MODEL_TIMEOUT", message="slow")


def test_model_failure_refunds_and_reports(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(service, "get_image_provider", lambda _s: Timeout())
    target, source = two(world)
    with events.subscribe(world["watch"]) as sub:
        r = put(client, target, source)
        seen = collect(sub)
    assert r.status_code == 202
    assert results(world, target) == []
    failed = [e for e in seen if e["type"] == "put.failed"]
    assert len(failed) == 1 and failed[0]["data"]["code"] == "MODEL_TIMEOUT"
    assert failed[0]["data"]["job_id"] == r.json()["job_id"] and failed[0]["data"]["message"]
    assert not [e for e in seen if e["type"] in ("item.added", "put.done")]
    assert renders(world) == 0


def test_source_removed_before_the_job_runs(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append({"name": name, **kw}))
    target, source = two(world)
    r = put(client, target, source)
    assert r.status_code == 202
    (job,) = queued
    assert job.pop("name") == service.JOB and job["job_id"] == r.json()["job_id"]
    assert renders(world) == 1
    assert client.delete(f"/api/items/{source}").status_code == 204
    with events.subscribe(world["watch"]) as sub:
        service.put_into_job(**job)
        seen = collect(sub)
    failed = [e for e in seen if e["type"] == "put.failed"]
    assert len(failed) == 1 and failed[0]["data"]["code"] == "ITEM_NOT_FOUND"
    assert results(world, target) == []
    assert renders(world) == 0


def test_unexpected_error_refunds_and_reports(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "paste_into", boom)
    target, source = two(world)
    with events.subscribe(world["watch"]) as sub:
        assert put(client, target, source).status_code == 202
        seen = collect(sub)
    failed = [e for e in seen if e["type"] == "put.failed"]
    assert len(failed) == 1 and failed[0]["data"]["code"] == "PUT_ERROR"
    assert results(world, target) == []
    assert renders(world) == 0


def _with_alpha(world: dict[str, Any], item_id: str) -> np.ndarray:
    """Give the item an RGBA picture whose left half is transparent; returns its alpha."""
    img = Image.new("RGBA", (200, 100), (200, 120, 40, 255))
    a = np.full((100, 200), 255, dtype=np.uint8)
    a[:, :100] = 0
    img.putalpha(Image.fromarray(a))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    sha = files.sha256_hex(data)
    s = world["session"]
    item = s.get(BoardItem, item_id)
    item.storage_path, item.sha256 = files.save_original(data, sha, "png"), sha
    item.width, item.height, item.mime = 200, 100, "image/png"
    s.commit()
    return a


def test_subject_uses_an_extracted_cut_out(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    alpha = _with_alpha(world, source)
    s = world["session"]
    subject, _name = service.subject_of(s, s.get(BoardItem, source))
    assert subject.mode == "RGBA" and (np.asarray(subject.getchannel("A")) == alpha).all()

    pasted: list[Image.Image] = []
    real = render.paste_into

    def spy(t: Image.Image, subj: Image.Image, boxes: list[Any]) -> Image.Image:
        pasted.append(subj)
        return real(t, subj, boxes)

    monkeypatch.setattr(service, "paste_into", spy)
    assert put(client, target, source).status_code == 202
    (subj,) = pasted
    assert subj.mode == "RGBA" and (np.asarray(subj.getchannel("A")) == alpha).all()


def test_subject_is_the_one_image_part_cut_out(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    _target, source = two(world)
    s = world["session"]
    for p in s.scalars(select(ItemPart).where(ItemPart.item_id == source)):
        s.delete(p)
    s.add(ItemPart(item_id=source, key="wheel", label="Wheel", region_kind="box",
                   region_json=[0.1, 0.1, 0.9, 0.9], source="ai"))  # fmt: skip
    s.commit()
    item = s.get(BoardItem, source)
    subject, _name = service.subject_of(s, item)
    assert subject.mode == "RGBA"
    assert subject.size == (round(0.9 * item.width) - round(0.1 * item.width),
                            round(0.9 * item.height) - round(0.1 * item.height))  # fmt: skip


def test_a_part_spot_is_located_and_named(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    s = world["session"]
    s.add(ItemPart(item_id=target, key="front_wheel", label="Front wheel", region_kind="box",
                   region_json=[0.1, 0.5, 0.4, 0.9], source="ai"))  # fmt: skip
    s.commit()
    assert put(client, target, source, spots=[{"part": "front_wheel"}]).status_code == 202
    (item,) = results(world, target)
    assert "Front wheel" in item.generation_json["prompt"]


def held(world: dict[str, Any]) -> dict[str, Any]:
    return extract._reserved.get(world["watch"], {})


def test_queued_puts_reserve_their_slots_until_the_job_ends(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda name, **kw: queued.append(kw))
    target, source = two(world)
    a = put(client, target, source).json()
    b = put(client, target, source).json()  # the first picture does not exist yet
    assert (a["x"], a["y"]) != (b["x"], b["y"]) and len(held(world)) == 2
    service.put_into_job(**queued[0])  # success releases
    assert set(held(world)) == {queued[1]["job_id"]}
    assert len(results(world, target)) == 1
    monkeypatch.setattr(service, "get_image_provider", lambda _s: Timeout())
    service.put_into_job(**queued[1])  # a model failure releases
    assert held(world) == {}


def test_unexpected_failure_and_refusal_leave_no_put_reservation(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    assert put(client, target, target).status_code == 422
    assert held(world) == {}  # a refused request reserves nothing

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "paste_into", boom)
    assert put(client, target, source).status_code == 202
    assert held(world) == {}  # the catch-all wrapper released it


def test_a_failed_put_request_releases_its_reservation(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    target, source = two(world)
    service.request_put_into(s, target, source, CENTRE, None)
    assert len(held(world)) == 1
    s.rollback()  # the request's transaction did not commit
    assert held(world) == {}


def test_a_put_result_is_read_like_any_new_picture(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    target, source = two(world)
    assert put(client, target, source).status_code == 202
    (item,) = results(world, target)
    assert item.parse_status == "completed"  # queued for analysis, not left pending forever


def test_put_result_has_check(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.providers.reasoning import MockReasoningProvider

    asked: list[str] = []

    def no(_self: Any, _images: list[bytes], prompt: str) -> dict[str, Any]:
        asked.append(prompt)
        return {"answer": "no", "confidence": 0.7, "box": None, "note": "not there"}

    monkeypatch.setattr(MockReasoningProvider, "check_target", no)
    target, source = two(world)
    assert put(client, target, source, words="a red lamp").status_code == 202
    (item,) = results(world, target)
    assert item.check_json == {"target_ok": False, "answer": "no"}
    assert "a red lamp" in asked[0]
    listed = client.get(f"/api/boards/{world['watch']}/items").json()
    listed = listed["items"] if isinstance(listed, dict) else listed
    assert next(i for i in listed if i["id"] == item.id)["check"]["answer"] == "no"


def test_put_check_failure_leaves_the_result_unchecked(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.providers.reasoning import MockReasoningProvider

    def down(*_a: Any, **_k: Any) -> Any:
        raise ModelError("MODEL_TIMEOUT", message="slow")

    monkeypatch.setattr(MockReasoningProvider, "check_target", down)
    target, source = two(world)
    assert put(client, target, source).status_code == 202
    (item,) = results(world, target)
    assert item.check_json is None and renders(world) == 1
