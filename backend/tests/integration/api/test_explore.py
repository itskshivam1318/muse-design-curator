"""Explore: named text options per (item, attribute), stored, extended and listed per board."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import demo, events
from app.db.models import ItemAttribute
from app.db.repos import boards as boards_repo
from app.db.repos import lenses as lenses_repo
from app.domain.lens import load_curated_lens
from app.explore import service
from tests.integration.runs.test_orchestrator import source_with


def opt(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name, "description": f"{name} on this item.", "distance": "near",
        "value": name, "keeps": [], "edit_prompt": f"Change only the markers to {name}.", **over,
    }  # fmt: skip


class FakeReasoning:
    """Returns the given batches of raw options in turn and records each prompt."""

    id = "fake"
    model = "fake-reasoning"
    is_mock = True

    def __init__(self, *batches: list[Any]) -> None:
        self.batches = list(batches)
        self.prompts: list[str] = []
        self.images: list[list[bytes]] = []

    def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.images.append(images)
        return {"options": self.batches.pop(0)}


def fake(monkeypatch: pytest.MonkeyPatch, *batches: list[Any]) -> FakeReasoning:
    f = FakeReasoning(*batches)
    monkeypatch.setattr(service, "get_reasoning", lambda _settings: f)
    return f


SIX = [opt(n) for n in ("Sector dial", "Only the 12", "Roman numerals", "Breguet", "Dots", "Bars")]


def source(world: dict[str, Any]) -> str:
    return source_with(world, world["watch"], "markers")


def explore(client: TestClient, item: str, **body: Any):  # type: ignore[no-untyped-def]
    return client.post(f"/api/items/{item}/explore", json={"key": "markers", **body})


def board_list(client: TestClient, world: dict[str, Any]) -> list[dict[str, Any]]:
    r = client.get(f"/api/boards/{world['watch']}/explorations")
    assert r.status_code == 200
    return r.json()["explorations"]  # type: ignore[no-any-return]


def error(r: Any) -> str:
    return r.json()["error"]["code"]  # type: ignore[no-any-return]


def test_explore_creates_options_on_first_call(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    item = source(world)
    r = explore(client, item)
    assert r.status_code == 200, r.json()
    got = r.json()
    assert got["item_id"] == item and got["key"] == "markers" and got["board_id"] == world["watch"]
    opts = got["options"]
    assert 6 <= len(opts) <= 10
    assert [o["name"] for o in opts] == [f"Option {c}" for c in "ABCDEFGH"]
    assert all(o["batch"] == 1 and o["status"] == "open" for o in opts)
    assert all(o["x"] is None and o["y"] is None and o["parent_option_id"] is None for o in opts)
    assert opts[0]["value"] == "option_a" and opts[0]["distance"] == "near"
    assert opts[0]["edit_prompt"] and opts[0]["description"]


def test_explore_sends_the_full_original_image(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.db.repos import items as items_repo
    from app.storage import files

    f = fake(monkeypatch, SIX)
    item = source(world)
    assert explore(client, item).status_code == 200
    row = items_repo.get(world["session"], item)
    assert row is not None and row.storage_path
    assert f.images[0] == [files.abs_path(row.storage_path).read_bytes()]
    assert "Markers" in f.prompts[0]


def test_more_appends_without_repeats(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    more = [opt("sector DIAL"), opt(" Only the 12 "), opt("Devanagari"), opt("Lumed plots"),
            opt("devanagari")]  # fmt: skip
    f = fake(monkeypatch, SIX, more)
    item = source(world)
    explore(client, item)
    r = explore(client, item, mode="more")
    assert r.status_code == 200, r.json()
    opts = r.json()["options"]
    assert [o["name"] for o in opts] == [o["name"] for o in SIX] + ["Devanagari", "Lumed plots"]
    assert [o["batch"] for o in opts[-2:]] == [2, 2]
    assert "Sector dial" in f.prompts[1] and "do not repeat" in f.prompts[1].lower()


def test_further_asks_for_bolder(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    f = fake(monkeypatch, SIX, [opt("Hidden hours", distance="wild")])
    item = source(world)
    explore(client, item)
    r = explore(client, item, mode="further")
    assert r.status_code == 200 and r.json()["options"][-1]["distance"] == "wild"
    assert "bolder" in f.prompts[1].lower()


def test_steer_stored_per_batch(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    f = fake(monkeypatch, SIX, [opt("Devanagari"), opt("Kanji")])
    item = source(world)
    explore(client, item)
    r = explore(client, item, steer="only non-Latin scripts", mode="more")
    opts = r.json()["options"]
    assert {o["steer"] for o in opts if o["batch"] == 1} == {None}
    assert {o["steer"] for o in opts if o["batch"] == 2} == {"only non-Latin scripts"}
    assert "only non-Latin scripts" in f.prompts[1]


def test_steer_longer_than_200_is_rejected(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = explore(client, source(world), steer="x" * 201)
    assert r.status_code == 400 and error(r) == "VALIDATION_ERROR"


def test_branch_sets_parent(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    f = fake(monkeypatch, SIX, [opt("Sector dial, two-tone"), opt("Sector dial, railway track")])
    item = source(world)
    parent = explore(client, item).json()["options"][0]
    r = explore(client, item, parent_option_id=parent["id"])
    assert r.status_code == 200, r.json()
    kids = [o for o in r.json()["options"] if o["parent_option_id"] == parent["id"]]
    assert [k["name"] for k in kids] == ["Sector dial, two-tone", "Sector dial, railway track"]
    assert "Sector dial" in f.prompts[1] and "deeper" in f.prompts[1].lower()


def test_branch_from_another_exploration_is_404(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake(monkeypatch, SIX, SIX)
    item = source(world)
    parent = explore(client, item).json()["options"][0]
    r = client.post(f"/api/items/{item}/explore",
                    json={"key": "hands", "parent_option_id": parent["id"]})  # fmt: skip
    assert r.status_code == 404 and error(r) == "OPTION_NOT_FOUND"
    r = explore(client, item, parent_option_id="opt_missing")
    assert r.status_code == 404 and error(r) == "OPTION_NOT_FOUND"


def test_same_item_key_reuses_exploration(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake(monkeypatch, SIX, [opt("Devanagari")], SIX)
    item = source(world)
    first = explore(client, item).json()
    again = explore(client, item).json()
    assert again["id"] == first["id"] and len(again["options"]) == 7
    other = client.post(f"/api/items/{item}/explore", json={"key": "hands"}).json()
    assert other["id"] != first["id"]
    assert sorted(e["key"] for e in board_list(client, world)) == ["hands", "markers"]


def test_keeps_are_filtered_to_known_keys(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    keeps = ["hands", "markers", "not_a_key", "hands", "case_material"]
    fake(monkeypatch, [opt("Devanagari", keeps=keeps)])
    r = explore(client, source(world))
    assert r.json()["options"][0]["keeps"] == ["hands", "case_material"]


def test_missing_edit_prompt_gets_a_default(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake(monkeypatch, [opt("Devanagari", edit_prompt="  ")])
    o = explore(client, source(world)).json()["options"][0]
    assert "Markers" in o["edit_prompt"] and "Devanagari" in o["edit_prompt"]


def test_unparsed_item_still_explores(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    item = source(world)
    s.execute(delete(ItemAttribute).where(ItemAttribute.item_id == item))
    s.commit()
    r = explore(client, item)
    assert r.status_code == 200, r.json()
    assert len(r.json()["options"]) == 8


def test_all_junk_returns_502_explore_empty(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    junk = ["not an object", {"name": "   "}, opt("Far away", distance="far"), opt("Blank", value=" "),
            {"description": "no name"}, 7]  # fmt: skip
    fake(monkeypatch, junk)
    r = explore(client, source(world))
    assert r.status_code == 502 and error(r) == "EXPLORE_EMPTY"
    assert board_list(client, world) == []  # nothing stored


def test_only_repeats_returns_502(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake(monkeypatch, SIX, [opt("SECTOR DIAL"), opt("Bars")])
    item = source(world)
    explore(client, item)
    r = explore(client, item, mode="more")
    assert r.status_code == 502 and error(r) == "EXPLORE_EMPTY"
    assert len(board_list(client, world)[0]["options"]) == 6


def test_model_error_is_502(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.providers.reliability import ModelError

    class Down(FakeReasoning):
        def explore_options(self, images: list[bytes], prompt: str) -> dict[str, Any]:
            raise ModelError("MODEL_UNAVAILABLE", message="down")

    monkeypatch.setattr(service, "get_reasoning", lambda _s: Down())
    r = explore(client, source(world))
    assert r.status_code == 502 and error(r) == "MODEL_UNAVAILABLE"


def test_options_are_capped_at_ten(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake(monkeypatch, [opt(f"Move {n}") for n in range(14)])
    assert len(explore(client, source(world)).json()["options"]) == 10


def test_unknown_key_400(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"/api/items/{source(world)}/explore", json={"key": "wheel_count"})
    assert r.status_code == 400 and error(r) == "ATTRIBUTE_NOT_IN_LENS"


def test_unknown_item_404(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = explore(client, "itm_missing")
    assert r.status_code == 404 and error(r) == "ITEM_NOT_FOUND"


def test_shape_kind_400(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    full = load_curated_lens("watch", shape_enabled=True)
    assert full is not None
    lens = lenses_repo.save(s, world["watch"], "watch", "edited", full.model_dump(mode="json"),
                            status="confirmed")  # fmt: skip
    boards_repo.update(s, world["watch"], lens_id=lens.id)
    s.commit()
    r = client.post(f"/api/items/{source(world)}/explore", json={"key": "case_silhouette"})
    assert r.status_code == 400 and error(r) == "KIND_NOT_EXPLORABLE"


def test_board_without_lens_409(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    item = source(world)
    boards_repo.update(s, world["watch"], lens_id=None)
    s.commit()
    r = explore(client, item)
    assert r.status_code == 409 and error(r) == "LENS_REQUIRED"


def test_dismiss_hides_from_board_list(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    first = explore(client, source(world)).json()["options"][0]
    r = client.patch(f"/api/options/{first['id']}", json={"status": "dismissed"})
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    (listed,) = board_list(client, world)
    assert first["id"] not in [o["id"] for o in listed["options"]] and len(listed["options"]) == 7
    r = client.patch(f"/api/options/{first['id']}", json={"status": "open"})
    assert r.json()["status"] == "open" and len(board_list(client, world)[0]["options"]) == 8


def test_patch_rejects_other_statuses(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    first = explore(client, source(world)).json()["options"][0]
    r = client.patch(f"/api/options/{first['id']}", json={"status": "visualized"})
    assert r.status_code == 400


def test_patch_unknown_option_404(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = client.patch("/api/options/opt_missing", json={"x": 1})
    assert r.status_code == 404 and error(r) == "OPTION_NOT_FOUND"


def test_removed_source_hides_exploration(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    item = source(world)
    explore(client, item)
    assert len(board_list(client, world)) == 1
    assert client.delete(f"/api/items/{item}").status_code == 204
    assert board_list(client, world) == []


def test_board_list_unknown_board_404(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/boards/brd_missing/explorations")
    assert r.status_code == 404 and error(r) == "BOARD_NOT_FOUND"


def test_patch_saves_position(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    first = explore(client, source(world)).json()["options"][0]
    r = client.patch(f"/api/options/{first['id']}", json={"x": 120.5, "y": -40})
    assert r.status_code == 200 and (r.json()["x"], r.json()["y"]) == (120.5, -40.0)
    assert r.json()["status"] == "open"
    listed = board_list(client, world)[0]["options"][0]
    assert (listed["x"], listed["y"]) == (120.5, -40.0)


def test_feature_off_503(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    item = source(world)
    first = explore(client, item).json()["options"][0]
    monkeypatch.setenv("EXPLORE_ENABLED", "0")
    r = explore(client, item)
    assert r.status_code == 503 and error(r) == "FEATURE_OFF"
    r = client.patch(f"/api/options/{first['id']}", json={"x": 1})
    assert r.status_code == 503 and error(r) == "FEATURE_OFF"


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)


def test_demo_mode_locks_explore(demo_on, client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    item = source(world)
    for r in (explore(client, item), client.patch("/api/options/opt_x", json={"x": 1})):
        assert r.status_code == 403 and error(r) == "DEMO_LOCKED"
    assert client.get(f"/api/boards/{world['watch']}/explorations").status_code == 200
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    assert explore(client, item).status_code == 200


def test_explore_publishes_event(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    item = source(world)
    with events.subscribe(world["watch"]) as sub:
        got = explore(client, item).json()
        ev = _next_explore_event(sub)
        assert ev["data"]["id"] == got["id"] and len(ev["data"]["options"]) == 8
        client.patch(f"/api/options/{got['options'][0]['id']}", json={"status": "dismissed"})
        ev = _next_explore_event(sub)
        assert ev["data"]["id"] == got["id"] and len(ev["data"]["options"]) == 7


def _next_explore_event(sub: events.Subscription) -> dict[str, Any]:
    while (ev := sub.get(timeout=2)) is not None:
        if ev["type"] == "explore.updated":
            return ev
    raise AssertionError("no explore.updated event")
