"""Staged takes: visualize stages, keep un-stages one, un-keep puts it back."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import demo, events
from app.db.ids import now_iso
from app.db.models import BoardItem
from app.db.repos import items as items_repo
from tests.integration.api.test_explore import board_list, error, explore, source
from tests.integration.api.test_visualize import first_option, generated, option_row, run


def make_takes(client: TestClient, world: dict[str, Any], n: int = 2) -> tuple[str, list[str]]:
    opt = first_option(client, world)
    for _ in range(n):
        assert run(client, opt["id"]).status_code == 202
    return opt["id"], [i.id for i in generated(world, opt["id"])]


def fresh(world: dict[str, Any], item_id: str) -> BoardItem:
    s = world["session"]
    s.expire_all()
    item = s.get(BoardItem, item_id)
    assert item is not None
    return item


def keep(client: TestClient, option_id: str, item_id: str, **at: float):  # type: ignore[no-untyped-def]
    return client.post(f"/api/options/{option_id}/keep", json={"item_id": item_id, **at})


def test_visualize_creates_staged_take(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    assert run(client, opt["id"]).status_code == 202
    (item,) = generated(world, opt["id"])
    src = items_repo.get(world["session"], source(world))
    assert item.staged is True
    assert (item.x, item.y) == (src.x, src.y)  # not drawn: the source's spot
    assert option_row(world, opt["id"]).status == "visualized"
    listed = client.get(f"/api/boards/{world['watch']}/items").json()["items"]
    assert next(i for i in listed if i["id"] == item.id)["staged"] is True


def test_keep_unstages_and_sets_kept(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, _b) = make_takes(client, world)
    r = keep(client, oid, a, x=300, y=40)
    assert r.status_code == 200, r.json()
    assert r.json()["kept_item_id"] == a and r.json()["status"] == "kept"
    item = fresh(world, a)
    assert item.staged is False and (item.x, item.y) == (300, 40)
    assert option_row(world, oid).kept_item_id == a


def test_keep_twice_idempotent(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, b) = make_takes(client, world)
    assert keep(client, oid, a).status_code == 200
    assert keep(client, oid, a).status_code == 200
    assert fresh(world, a).staged is False and fresh(world, b).staged is True
    assert option_row(world, oid).status == "kept"


def test_keep_second_take_restages_first(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, b) = make_takes(client, world)
    keep(client, oid, a)
    r = keep(client, oid, b)
    assert r.json()["kept_item_id"] == b
    assert fresh(world, a).staged is True and fresh(world, b).staged is False


def test_unkeep_restages(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, _b) = make_takes(client, world)
    keep(client, oid, a)
    r = client.post(f"/api/options/{oid}/unkeep")
    assert r.status_code == 200
    assert r.json()["kept_item_id"] is None and r.json()["status"] == "visualized"
    assert fresh(world, a).staged is True
    again = client.post(f"/api/options/{oid}/unkeep")  # nothing kept: a no-op
    assert again.status_code == 200 and again.json()["status"] == "visualized"


def test_keep_wrong_option_400(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, _b) = make_takes(client, world)
    other = explore(client, source(world), mode="more").json()["options"][-1]["id"]
    r = keep(client, other, a)
    assert r.status_code == 400 and error(r) == "NOT_A_TAKE"
    assert keep(client, "nope", a).status_code == 404
    assert keep(client, oid, "nope").status_code == 404


def test_existing_unstaged_takes_untouched(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a,) = make_takes(client, world, n=1)
    old = fresh(world, a)
    old.staged = False  # a take made before takes were staged
    world["session"].commit()
    assert fresh(world, a).staged is False
    opt = next(o for o in board_list(client, world)[0]["options"] if o["id"] == oid)
    assert opt["takes"] == [a] and opt["status"] == "visualized"


def test_option_dict_lists_takes(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, b) = make_takes(client, world)
    keep(client, oid, b)
    opt = next(o for o in board_list(client, world)[0]["options"] if o["id"] == oid)
    assert opt["takes"] == [a, b] and opt["kept_item_id"] == b
    patched = client.patch(f"/api/options/{oid}", json={"x": 1, "y": 2}).json()
    assert patched["takes"] == [a, b]


def test_keep_publishes_events(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, b) = make_takes(client, world)
    keep(client, oid, a)
    with events.subscribe(world["watch"]) as sub:
        keep(client, oid, b)
        seen = []
        while (ev := sub.get(timeout=1)) is not None:
            seen.append((ev["type"], ev["data"].get("id")))
    updated = {i for t, i in seen if t == "item.updated"}
    assert updated == {a, b} and "explore.updated" in [t for t, _ in seen]


def test_staged_takes_leave_pools_and_dedupe(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    from app.lens_service import _eligible

    oid, (a, b) = make_takes(client, world)
    s = world["session"]
    ids = {i.id for i in _eligible(s, world["watch"])}
    assert a not in ids and b not in ids
    keep(client, oid, a)
    s.expire_all()
    assert a in {i.id for i in _eligible(s, world["watch"])}


def test_staged_source_cannot_be_explored(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    _oid, (a, _b) = make_takes(client, world)
    r = explore(client, a)
    assert r.status_code == 404


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)


def test_demo_mode_requires_unlock(demo_on: None, client: TestClient) -> None:
    client.cookies.clear()
    r = client.post("/api/options/x/keep", json={"item_id": "y"})
    assert r.status_code == 403 and error(r) == "DEMO_LOCKED"
    r = client.post("/api/options/x/unkeep")
    assert r.status_code == 403 and error(r) == "DEMO_LOCKED"
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    assert client.post("/api/options/x/unkeep").status_code == 404


def test_keep_during_visualizing_keeps_the_claim(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    from app.explore import visualize

    oid, (a, _b) = make_takes(client, world)
    o = option_row(world, oid)
    o.status, o.visualize_claimed_at = "visualizing", now_iso()
    world["session"].commit()
    r = keep(client, oid, a)
    assert r.status_code == 200 and r.json()["status"] == "visualizing"
    assert run(client, oid).status_code == 409  # claim still held
    world["session"].expire_all()
    visualize._settle(world["session"], oid, None)
    world["session"].commit()
    assert option_row(world, oid).status == "kept"


def test_keep_on_dismissed_option_409(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, _b) = make_takes(client, world)
    client.patch(f"/api/options/{oid}", json={"status": "dismissed"})
    r = keep(client, oid, a)
    assert r.status_code == 409 and error(r) == "OPTION_DISMISSED"
    assert fresh(world, a).staged is True


def test_keep_restages_every_other_take(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    oid, (a, b, c) = make_takes(client, world, n=3)
    for i in (a, b):  # two unstaged by older data
        fresh(world, i).staged = False
    world["session"].commit()
    keep(client, oid, c)
    assert [fresh(world, i).staged for i in (a, b, c)] == [True, True, False]


def test_upload_identical_to_staged_take_unstages_it(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    from app.storage import files

    _oid, (a, _b) = make_takes(client, world)
    item = fresh(world, a)
    data = files.abs_path(item.storage_path).read_bytes()
    r = client.post(
        f"/api/boards/{world['watch']}/items", files=[("files[]", ("same.png", data, "image/png"))]
    )
    assert r.status_code < 300, r.text
    assert fresh(world, a).staged is False


def test_upload_identical_to_take_of_dismissed_option_announces(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    from app.storage import files

    oid, (a, _b) = make_takes(client, world)
    client.patch(f"/api/options/{oid}", json={"status": "dismissed"})
    data = files.abs_path(fresh(world, a).storage_path).read_bytes()
    with events.subscribe(world["watch"]) as sub:
        r = client.post(
            f"/api/boards/{world['watch']}/items", files=[("files[]", ("s.png", data, "image/png"))]
        )
        assert r.status_code < 300, r.text
        seen = []
        while (ev := sub.get(timeout=1)) is not None:
            seen.append((ev["type"], ev["data"].get("id"), ev["data"].get("staged")))
    assert ("item.updated", a, False) in seen
    assert fresh(world, a).staged is False
