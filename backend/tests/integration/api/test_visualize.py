"""Visualize: edit the source image into a generated item, grow the vocabulary, check it."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import demo, events
from app.db.models import BoardItem, ExploreOption
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.repos import lenses as lenses_repo
from app.explore import check, visualize
from app.providers.reliability import ModelError
from tests.integration.api.test_explore import board_list, error, explore, source


def first_option(client: TestClient, world: dict[str, Any]) -> dict[str, Any]:
    r = explore(client, source(world))
    assert r.status_code == 200, r.json()
    return r.json()["options"][0]  # type: ignore[no-any-return]


def run(client: TestClient, option_id: str):  # type: ignore[no-untyped-def]
    return client.post(f"/api/options/{option_id}/visualize")


def generated(world: dict[str, Any], option_id: str) -> list[BoardItem]:
    s = world["session"]
    s.expire_all()
    q = select(BoardItem).where(BoardItem.explore_option_id == option_id).order_by(BoardItem.id)
    return list(s.scalars(q))


def option_row(world: dict[str, Any], option_id: str) -> ExploreOption:
    s = world["session"]
    s.expire_all()
    o = s.get(ExploreOption, option_id)
    assert o is not None
    return o


def item_dict(client: TestClient, world: dict[str, Any], item_id: str) -> dict[str, Any]:
    items = client.get(f"/api/boards/{world['watch']}/items").json()["items"]
    return next(i for i in items if i["id"] == item_id)  # type: ignore[no-any-return]


def test_visualize_creates_generated_item_with_lineage(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    r = run(client, opt["id"])
    assert r.status_code == 202, r.json()
    assert r.json() == {"option_id": opt["id"], "status": "visualizing"}

    (item,) = generated(world, opt["id"])
    src = items_repo.get(world["session"], source(world))
    assert src is not None
    assert item.origin == "generated" and item.rights_status == "generated"
    assert item.parent_item_id == src.id and item.board_id == world["watch"]
    assert item.kind == "image" and item.storage_path and item.thumb_path and item.sha256
    assert item.generation_json == {
        "model": "mock-image", "prompt": opt["edit_prompt"], "option_id": opt["id"]
    }  # fmt: skip
    # the option has no saved position: the fallback is right of the source, then past the note
    assert item.x == src.x + src.w + 40 + 260 and item.y == src.y
    assert item.parse_status == "completed"
    assert option_row(world, opt["id"]).status == "visualized"
    listed = next(o for o in board_list(client, world)[0]["options"] if o["id"] == opt["id"])
    assert listed["status"] == "visualized" and listed["last_error"] is None


def test_generated_item_sits_right_of_a_placed_note(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    client.patch(f"/api/options/{opt['id']}", json={"x": 100, "y": -50})
    assert run(client, opt["id"]).status_code == 202
    (item,) = generated(world, opt["id"])
    assert (item.x, item.y) == (360, -50)


def test_generated_item_dict_has_generation_and_no_licence(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    run(client, opt["id"])
    (item,) = generated(world, opt["id"])
    d = item_dict(client, world, item.id)
    assert d["licence"] is None and d["origin"] == "generated"
    assert d["rights_status"] == "generated" and d["explore_option_id"] == opt["id"]
    assert d["generation"]["model"] == "mock-image"
    assert set(d["check"]) == {"target", "kept", "of", "drifted"}
    assert d["check"]["target"]["answer"] in ("yes", "no", "unclear")


def test_second_visualize_while_running_409(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    s = world["session"]
    option_row(world, opt["id"]).status = "visualizing"
    s.commit()
    r = run(client, opt["id"])
    assert r.status_code == 409 and error(r) == "VISUALIZE_IN_PROGRESS"
    assert generated(world, opt["id"]) == []


def test_revisualize_after_done_creates_second_item(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    assert run(client, opt["id"]).status_code == 202
    assert run(client, opt["id"]).status_code == 202
    items = generated(world, opt["id"])
    assert len(items) == 2 and items[0].id != items[1].id
    assert option_row(world, opt["id"]).status == "visualized"


class BrokenImages:
    id = "broken"
    model = "broken-image"
    is_mock = True

    def edit(self, image: bytes, prompt: str) -> bytes:
        raise ModelError("MODEL_UNAVAILABLE", message="down")


def test_image_failure_resets_option_no_item(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(visualize, "get_image_provider", lambda _s: BrokenImages())
    opt = first_option(client, world)
    before = len(items_repo.list_active(world["session"], world["watch"]))
    assert run(client, opt["id"]).status_code == 202
    o = option_row(world, opt["id"])
    assert o.status == "open" and o.last_error == "MODEL_UNAVAILABLE"
    assert generated(world, opt["id"]) == []
    assert len(items_repo.list_active(world["session"], world["watch"])) == before


def test_image_failure_after_a_success_stays_visualized(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    run(client, opt["id"])
    monkeypatch.setattr(visualize, "get_image_provider", lambda _s: BrokenImages())
    run(client, opt["id"])
    o = option_row(world, opt["id"])
    assert o.status == "visualized" and o.last_error == "MODEL_UNAVAILABLE"
    assert len(generated(world, opt["id"])) == 1


def test_closed_enum_value_added_to_lens_vocab(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    s = world["session"]
    old = boards_repo.get(s, world["watch"])
    assert old is not None
    old_lens = old.lens_id
    opt = first_option(client, world)  # markers is a closed enum; mock values are new tokens
    run(client, opt["id"])
    s.expire_all()
    board = boards_repo.get(s, world["watch"])
    assert board is not None and board.lens_id != old_lens
    row = lenses_repo.get(s, board.lens_id)  # type: ignore[arg-type]
    assert row is not None and row.origin == "edited" and row.status == "confirmed"
    assert row.domain == "watch" and row.spec_json["id"] == f"watch@{row.version}"
    markers = next(a for a in row.spec_json["attributes"] if a["key"] == "markers")
    assert markers["vocabulary"][-1] == opt["value"]
    # visualizing it again does not add another version
    run(client, opt["id"])
    s.expire_all()
    assert boards_repo.get(s, world["watch"]).lens_id == row.id  # type: ignore[union-attr]


def test_check_target_answer_stored(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    asked: list[str] = []

    class Checker:
        def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
            asked.append(prompt)
            return {"answer": "yes", "confidence": 0.8, "box": [0.1, 0.2, 0.5, 0.6],
                    "note": "Devanagari numerals at every hour."}  # fmt: skip

    monkeypatch.setattr(check, "get_reasoning", lambda _s: Checker())
    opt = first_option(client, world)
    run(client, opt["id"])
    (item,) = generated(world, opt["id"])
    assert item.check_json["target"] == {
        "answer": "yes", "confidence": 0.8, "box": [0.1, 0.2, 0.5, 0.6],
        "note": "Devanagari numerals at every hour.",
    }  # fmt: skip
    assert opt["name"] in asked[0] and "Markers" in asked[0]


def test_parse_failure_keeps_item_with_check_error(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.extraction import service as extraction

    def down(*_a: Any, **_k: Any) -> Any:
        raise ModelError("MODEL_TIMEOUT", message="slow")

    monkeypatch.setattr(extraction, "model_extract", down)
    opt = first_option(client, world)
    run(client, opt["id"])
    (item,) = generated(world, opt["id"])
    assert item.parse_status == "failed"
    assert item.check_json == {"error": "MODEL_TIMEOUT"}
    assert option_row(world, opt["id"]).status == "visualized"


def test_check_model_failure_keeps_item_with_check_error(
    client: TestClient, world, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    class Down:
        def check_target(self, images: list[bytes], prompt: str) -> dict[str, Any]:
            raise ModelError("MODEL_UNAVAILABLE", message="down")

    monkeypatch.setattr(check, "get_reasoning", lambda _s: Down())
    opt = first_option(client, world)
    run(client, opt["id"])
    (item,) = generated(world, opt["id"])
    assert item.check_json == {"error": "MODEL_UNAVAILABLE"}
    assert option_row(world, opt["id"]).status == "visualized"


def test_visualize_publishes_events(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    with events.subscribe(world["watch"]) as sub:
        run(client, opt["id"])
        seen: list[dict[str, Any]] = []
        while (ev := sub.get(timeout=0.5)) is not None:
            seen.append(ev)
    types = [e["type"] for e in seen]
    explores = [e for e in seen if e["type"] == "explore.updated"]
    status = [next(o["status"] for o in e["data"]["options"] if o["id"] == opt["id"])
              for e in explores]  # fmt: skip
    assert status[0] == "visualizing" and status[-1] == "visualized"
    added = next(e for e in seen if e["type"] == "item.added")
    assert (
        added["data"]["origin"] == "generated" and added["data"]["explore_option_id"] == opt["id"]
    )
    updated = [
        e for e in seen if e["type"] == "item.updated" and e["data"]["id"] == added["data"]["id"]
    ]
    assert updated and "target" in updated[-1]["data"]["check"]
    assert types.index("item.added") < types.index("item.updated")
    last_explore = max(i for i, t in enumerate(types) if t == "explore.updated")
    assert types.index("item.updated") < last_explore


def test_reopened_option_with_images_is_visualized(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    run(client, opt["id"])
    client.patch(f"/api/options/{opt['id']}", json={"status": "dismissed"})
    r = client.patch(f"/api/options/{opt['id']}", json={"status": "open"})
    assert r.status_code == 200 and r.json()["status"] == "visualized"


def test_reopened_option_whose_images_were_removed_is_open(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    run(client, opt["id"])
    (item,) = generated(world, opt["id"])
    assert client.delete(f"/api/items/{item.id}").status_code == 204
    client.patch(f"/api/options/{opt['id']}", json={"status": "dismissed"})
    r = client.patch(f"/api/options/{opt['id']}", json={"status": "open"})
    assert r.json()["status"] == "open"


def test_unknown_option_404(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    r = run(client, "opt_missing")
    assert r.status_code == 404 and error(r) == "OPTION_NOT_FOUND"


def test_feature_off_503(client: TestClient, world, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    opt = first_option(client, world)
    monkeypatch.setenv("EXPLORE_ENABLED", "0")
    r = run(client, opt["id"])
    assert r.status_code == 503 and error(r) == "FEATURE_OFF"


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    demo.reset()
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)


def test_demo_mode_locks_visualize(demo_on, client: TestClient, world) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    opt = first_option(client, world)
    client.cookies.clear()
    r = run(client, opt["id"])
    assert r.status_code == 403 and error(r) == "DEMO_LOCKED"
    assert generated(world, opt["id"]) == []
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    assert run(client, opt["id"]).status_code == 202
