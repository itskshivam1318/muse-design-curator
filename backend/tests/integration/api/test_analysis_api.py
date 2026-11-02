"""Per-board daily limits as the API reports them."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import demo
from app.analysis import service
from app.api import deps
from app.board import profile_hook
from app.db.models import BoardItem
from app.db.repos import attributes as attrs_repo
from app.db.repos import explore as explore_repo
from app.storage import files
from tests.integration.api.test_explore import explore, source
from tests.integration.api.test_visualize import first_option, run
from tests.media import image_bytes

MESSAGE = "Daily limit reached for this board, try tomorrow."


def test_explore_stops_at_the_daily_analyse_limit(
    client: TestClient, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYSE_PER_BOARD_PER_DAY", "1")
    assert explore(client, source(world)).status_code == 200
    r = explore(client, source(world))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "DAILY_LIMIT"
    assert r.json()["error"]["message"] == MESSAGE


def test_visualize_stops_at_the_daily_render_limit(
    client: TestClient, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER_PER_BOARD_PER_DAY", "1")
    opt = first_option(client, world)
    assert run(client, opt["id"]).status_code == 202
    r = run(client, opt["id"])
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "DAILY_LIMIT"
    assert r.json()["error"]["message"] == MESSAGE


# ---- the routes of the analysis loop ----


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)


def new_board(client: TestClient, title: str = "B") -> str:
    return client.post("/api/boards", json={"title": title}).json()["id"]  # type: ignore[no-any-return]


def upload(client: TestClient, board: str, seed: int = 0) -> str:
    r = client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", (f"a{seed}.png", image_bytes(seed=seed), "application/octet-stream"))],
    )
    assert r.status_code == 200, r.json()
    return r.json()["results"][0]["item"]["id"]  # type: ignore[no-any-return]


@pytest.fixture
def item(client: TestClient, quiet: None) -> tuple[str, str]:
    board = new_board(client)
    return board, upload(client, board)


def db() -> Session:
    return deps._factory()()


def test_get_analysis_shape(client: TestClient, item: tuple[str, str]) -> None:
    _board, item_id = item
    r = client.get(f"/api/items/{item_id}/analysis")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert (body["content_type"], body["parse_status"]) == ("image", "completed")
    assert {p["key"] for p in body["parts"]} == {"body", "detail"}
    assert set(body["parts"][0]) == {"key", "label", "region_kind", "region", "mask_url", "source"}
    assert body["parts"][0]["mask_url"] is None
    dims = {d["key"]: d for d in body["dimensions"]}
    assert set(dims["subject"]) == {
        "key", "label", "type", "part", "prompt", "kind", "value", "confidence", "source",
        "status",
    }  # fmt: skip
    assert dims["subject"]["type"] == "abstract" and dims["subject"]["source"] == "ai"
    assert dims["body_colour"]["type"] == "physical" and dims["body_colour"]["part"] == "body"
    assert client.get("/api/items/nope/analysis").status_code == 404


def test_analysis_omits_removed_and_marks_stale(client: TestClient, item: tuple[str, str]) -> None:
    _board, item_id = item
    assert client.delete(f"/api/items/{item_id}/parts/detail").status_code == 204
    assert client.delete(f"/api/items/{item_id}/dimensions/subject").status_code == 204
    with db() as s:
        row = next(r for r in attrs_repo.for_item(s, item_id) if r.key == "body_colour")
        row.status = "stale"
        s.commit()
    body = client.get(f"/api/items/{item_id}/analysis").json()
    assert [p["key"] for p in body["parts"]] == ["body"]
    keys = {d["key"]: d["status"] for d in body["dimensions"]}
    assert "subject" not in keys and "detail_style" not in keys  # the part's dimensions went too
    assert keys["body_colour"] == "stale"


def test_analyse_route_queues_and_counts(
    client: TestClient, item: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    board, item_id = item
    monkeypatch.setenv("ANALYSE_PER_BOARD_PER_DAY", str(demo_used(board) + 1))
    r = client.post(f"/api/items/{item_id}/analyse")
    assert r.status_code == 202 and r.json() == {"parse_status": "pending"}
    limited = client.post(f"/api/items/{item_id}/analyse")
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "DAILY_LIMIT"
    assert client.post("/api/items/nope/analyse").status_code == 404


def demo_used(board_id: str) -> int:
    return len(demo.windows._hits.get(f"analyse:{board_id}", ()))


def test_analyse_route_while_processing_is_409(client: TestClient, item: tuple[str, str]) -> None:
    board, item_id = item
    with db() as s:
        s.get(BoardItem, item_id).parse_status = "processing"  # type: ignore[union-attr]
        s.commit()
    r = client.post(f"/api/items/{item_id}/analyse")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PARSE_IN_PROGRESS"
    assert demo_used(board) == 1  # the refused request took no slot beyond the upload's


def test_region_of_a_mask_part_resolves_through_the_media_route(
    client: TestClient, item: tuple[str, str]
) -> None:
    _board, item_id = item
    r = client.get(f"/api/items/{item_id}/parts/body/region")
    assert r.status_code == 200, r.json()
    region = r.json()
    assert region["kind"] == "mask" and region["mask_url"].startswith("/api/media/masks/")
    served = client.get(region["mask_url"])
    assert served.status_code == 200 and served.content[:4] == b"\x89PNG"
    part = next(
        p
        for p in client.get(f"/api/items/{item_id}/analysis").json()["parts"]
        if p["key"] == "body"
    )
    assert part["mask_url"] == region["mask_url"]
    assert isinstance(part["region"], list) and len(part["region"]) == 4  # the raw box
    assert client.get(f"/api/items/{item_id}/parts/nope/region").status_code == 404


@pytest.mark.parametrize(
    "name",
    ["..%2F..%2Fetc%2Fpasswd", "..", "x.png", f"{'a' * 64}-{'b' * 12}.png"],  # last: not on disk
)
def test_mask_media_route_refuses_other_names(
    client: TestClient, item: tuple[str, str], name: str
) -> None:
    assert client.get(f"/api/media/masks/{name}").status_code == 404


def test_mask_media_route_does_not_serve_other_files(
    client: TestClient, item: tuple[str, str]
) -> None:
    sha = files.sha256_hex(b"x")
    assert client.get(f"/api/media/masks/{sha}-{'0' * 12}.png").status_code == 404
    assert client.get(f"/api/media/masks/{sha}.webp").status_code == 404


def test_part_create_rename_remove(client: TestClient, item: tuple[str, str]) -> None:
    _board, item_id = item
    r = client.post(
        f"/api/items/{item_id}/parts",
        json={"label": "Dial", "region": {"kind": "box", "box": [0.1, 0.1, 0.5, 0.5]}},
    )
    assert r.status_code == 201, r.json()
    assert r.json() | {"mask_url": None} == {
        "key": "dial", "label": "Dial", "region_kind": "box", "region": [0.1, 0.1, 0.5, 0.5],
        "mask_url": None, "source": "you",
    }  # fmt: skip
    r = client.patch(f"/api/items/{item_id}/parts/dial", json={"label": "Face"})
    assert r.status_code == 200 and r.json()["label"] == "Face" and r.json()["key"] == "dial"
    assert client.post(f"/api/items/{item_id}/parts", json={"label": "Dial"}).status_code == 409
    assert client.delete(f"/api/items/{item_id}/parts/dial").status_code == 204
    assert client.delete(f"/api/items/{item_id}/parts/dial").status_code == 404
    keys = [p["key"] for p in client.get(f"/api/items/{item_id}/analysis").json()["parts"]]
    assert "dial" not in keys


def test_add_part_by_name_alone(client: TestClient, item: tuple[str, str]) -> None:
    """What the Whole item card's "+ Add part" sends ({label}): fine on an image, refused on a
    UI screenshot (no segmentation for UI) and on a note (it needs a text range)."""
    board, item_id = item
    assert client.post(f"/api/items/{item_id}/parts", json={"label": "Lid"}).status_code == 201
    with db() as s:
        s.get(BoardItem, item_id).content_type = "ui"  # type: ignore[union-attr]
        s.commit()
    r = client.post(f"/api/items/{item_id}/parts", json={"label": "Header"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REGION_REQUIRED"
    boxed = {"label": "Header", "region": {"kind": "box", "box": [0, 0, 1, 0.2]}}
    assert client.post(f"/api/items/{item_id}/parts", json=boxed).status_code == 201
    note = client.post(f"/api/boards/{board}/notes", json={"text": "A tall jar", "x": 0, "y": 0})
    r = client.post(f"/api/items/{note.json()['id']}/parts", json={"label": "Jar"})
    assert r.status_code == 400


def test_dimension_create_update_remove(client: TestClient, item: tuple[str, str]) -> None:
    _board, item_id = item
    r = client.post(
        f"/api/items/{item_id}/dimensions",
        json={"label": "Warmth", "type": "abstract", "prompt": "How warm is it?"},
    )
    assert r.status_code == 201, r.json()
    assert (r.json()["key"], r.json()["source"], r.json()["status"]) == (
        "warmth",
        "you",
        "missing",
    )
    r = client.patch(f"/api/items/{item_id}/dimensions/warmth", json={"prompt": "Warm or cool?"})
    assert r.status_code == 200 and r.json()["prompt"] == "Warm or cool?"
    r = client.post(
        f"/api/items/{item_id}/dimensions",
        json={"label": "Hue", "type": "physical", "part": "body", "kind": "color"},
    )
    assert r.status_code == 201 and r.json()["part"] == "body" and r.json()["type"] == "physical"
    assert client.delete(f"/api/items/{item_id}/dimensions/warmth").status_code == 204
    keys = [d["key"] for d in client.get(f"/api/items/{item_id}/analysis").json()["dimensions"]]
    assert "warmth" not in keys and "hue" in keys


def test_whole_item_add_dimension_by_name_alone(client: TestClient, item: tuple[str, str]) -> None:
    """Exactly what the Whole item card's "+ Add dimension" sends: a label, no prompt."""
    _board, item_id = item
    r = client.post(
        f"/api/items/{item_id}/dimensions",
        json={"label": "Mood board fit", "type": "abstract", "part": None},
    )
    assert r.status_code == 201, r.json()
    assert r.json()["type"] == "abstract"
    assert r.json()["prompt"] == "What is the Mood board fit of this item?"


def test_patch_item_sets_content_type_and_reanalyses(
    client: TestClient, item: tuple[str, str]
) -> None:
    _board, item_id = item
    r = client.patch(f"/api/items/{item_id}", json={"content_type": "ui"})
    assert r.status_code == 200, r.json()
    assert r.json()["content_type"] == "ui" and r.json()["extracted_part"] is None
    assert client.patch(f"/api/items/{item_id}", json={"content_type": "bad"}).status_code == 400
    with db() as s:
        row = s.get(BoardItem, item_id)
        assert row is not None and row.content_type == "ui" and row.content_type_locked


def test_extract_route_returns_the_new_item(client: TestClient, item: tuple[str, str]) -> None:
    board, item_id = item
    r = client.post(f"/api/items/{item_id}/parts/body/extract")
    assert r.status_code == 200, r.json()
    child = r.json()
    assert child["parent_item_id"] == item_id and child["extracted_part"] == "body"
    assert child["board_id"] == board and child["kind"] == "image" and child["staged"] is False
    assert client.post(f"/api/items/{item_id}/parts/nope/extract").status_code == 404


def test_analyse_route_twice_costs_one_slot_and_one_job(
    client: TestClient, item: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    board, item_id = item
    queued: list[str] = []
    monkeypatch.setattr(service.jobs, "enqueue", lambda name, **kw: queued.append(kw["item_id"]))
    before = demo_used(board)
    assert client.post(f"/api/items/{item_id}/analyse").status_code == 202
    again = client.post(f"/api/items/{item_id}/analyse")
    assert again.status_code == 409 and again.json()["error"]["code"] == "PARSE_IN_PROGRESS"
    assert demo_used(board) == before + 1
    assert queued == [item_id]


@pytest.mark.parametrize(
    ("status", "code", "content_type"),
    [
        ("failed", "DAILY_LIMIT", "image"),  # over the limit at upload
        ("failed", "PARSE_ERROR", "image"),
        ("pending_lens", None, None),  # waiting for a lens (the old flow)
        ("completed", None, None),  # a legacy item: analysed by a lens, never by the analyser
    ],
)
def test_reanalyse_from_any_resting_status(
    client: TestClient, item: tuple[str, str], status: str, code: str | None,
    content_type: str | None,
) -> None:  # fmt: skip
    """Exactly what the toolbar's Re-analyse sends: POST /analyse with no body."""
    _board, item_id = item
    with db() as s:
        row = s.get(BoardItem, item_id)
        assert row is not None
        row.parse_status, row.parse_error_code, row.content_type = status, code, content_type
        s.commit()
    r = client.post(f"/api/items/{item_id}/analyse")
    assert r.status_code == 202, r.json()
    body = client.get(f"/api/items/{item_id}/analysis").json()
    assert body["parse_status"] == "completed" and body["content_type"] == "image"
    assert body["dimensions"]


def test_renderers_route(client: TestClient, item: tuple[str, str]) -> None:
    _board, item_id = item
    r = client.get(f"/api/items/{item_id}/dimensions/body_colour/renderers")
    assert r.status_code == 200, r.json()
    (first, *_rest) = r.json()
    assert first == {
        "id": "muse_image", "title": "Generate image",
        "detail": "Muse Image · inside the Body mask", "builtin": True,
    }  # fmt: skip
    abstract = client.get(f"/api/items/{item_id}/dimensions/subject/renderers").json()
    assert abstract[0]["detail"] == "Muse Image · whole image, no mask"
    assert client.get(f"/api/items/{item_id}/dimensions/nope/renderers").status_code == 404


def test_renderers_of_a_legacy_exploration_without_a_dimension_row(
    client: TestClient, item: tuple[str, str]
) -> None:
    """An exploration made under a lens whose key the item no longer has as a row: treated as
    an abstract dimension, not a 404."""
    board, item_id = item
    with db() as s:
        explore_repo.get_or_create(s, board, item_id, "old_markers")
        s.commit()
    r = client.get(f"/api/items/{item_id}/dimensions/old_markers/renderers")
    assert r.status_code == 200, r.json()
    assert r.json()[0]["detail"] == "Muse Image · whole image, no mask"
    with db() as s:  # a dimension the person removed stays gone, exploration or not
        explore_repo.get_or_create(s, board, item_id, "subject")
        s.commit()
    assert client.delete(f"/api/items/{item_id}/dimensions/subject").status_code == 204
    assert client.get(f"/api/items/{item_id}/dimensions/subject/renderers").status_code == 404


def add_row(session: Session, item_id: str, key: str, **kw: Any) -> None:
    fields: dict[str, Any] = {
        "label": key.title(), "category": "abstract", "kind": "enum", "value_json": "x",
        "confidence": 0.9, "status": "extracted", "source": "model", "dim_type": "abstract",
        "prompt": f"What is the {key}?",
    }  # fmt: skip
    attrs_repo.upsert(session, item_id, key, **{**fields, **kw})


def seed_recurring(client: TestClient) -> str:
    """A board whose two items both have "Colour" on Strap and on Dial, and "Mood"."""
    board = new_board(client)
    ids = [upload(client, board, seed) for seed in (1, 2)]
    with db() as s:
        for i in ids:
            for part in ("strap", "dial"):
                add_row(s, i, f"{part}_colour", label="Colour", part=part, dim_type="physical",
                        category="physical", kind="color")  # fmt: skip
            add_row(s, i, "mood", label="Mood")
        s.commit()
    return board


def offer_keys(body: dict[str, Any]) -> set[tuple[str, str | None]]:
    return {(o["label"], o["part"]) for o in body["offers"]}


def test_board_context_and_offers(client: TestClient, quiet: None) -> None:
    board = seed_recurring(client)
    client.patch(f"/api/boards/{board}", json={"context": "quiet watches"})
    r = client.get(f"/api/boards/{board}/context")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert (
        set(body) == {"your_words", "learned", "offers"} and body["your_words"] == "quiet watches"
    )
    assert isinstance(body["learned"], list)
    assert {"Colour", "Mood"} <= {o["label"] for o in body["offers"]}
    mood = next(o for o in body["offers"] if o["label"] == "Mood")
    assert mood == {
        "label": "Mood", "dim_type": "abstract", "kind": "enum", "count": 2, "total": 2,
        "part": None,
    }  # fmt: skip
    assert client.get("/api/boards/nope/context").status_code == 404


def test_accept_offer_is_keyed_by_part(client: TestClient, quiet: None) -> None:
    board = seed_recurring(client)
    assert offer_keys(client.get(f"/api/boards/{board}/context").json()) >= {
        ("Colour", "strap"), ("Colour", "dial"), ("Mood", None),
    }  # fmt: skip
    colour = {"label": "Colour", "dim_type": "physical", "kind": "color"}
    r = client.post(f"/api/boards/{board}/offers/accept", json={**colour, "part": "strap"})
    assert r.status_code == 200, r.json()
    assert set(r.json()) == {"your_words", "learned", "offers"}
    assert ("Colour", "strap") not in offer_keys(r.json())
    assert ("Colour", "dial") in offer_keys(r.json())  # the other part is still on offer
    assert ("Mood", None) in offer_keys(r.json())
    with db() as s:
        from app.db.repos import boards as boards_repo

        stored = boards_repo.get(s, board).dimensions_json  # type: ignore[union-attr]
        assert stored == [{**colour, "part": "strap"}]


def test_decline_offer_is_keyed_by_part_and_idempotent(client: TestClient, quiet: None) -> None:
    board = seed_recurring(client)
    body = {"label": "Colour", "dim_type": "physical", "kind": "color", "part": "dial"}
    first = client.post(f"/api/boards/{board}/offers/decline", json=body).json()
    again = client.post(f"/api/boards/{board}/offers/decline", json=body).json()
    assert first == again
    assert ("Colour", "dial") not in offer_keys(first) and ("Colour", "strap") in offer_keys(first)
    mood = {"label": "mood", "dim_type": "abstract", "kind": "enum"}
    r = client.post(f"/api/boards/{board}/offers/decline", json=mood)
    assert ("Mood", None) not in offer_keys(r.json())
    assert client.post("/api/boards/nope/offers/accept", json=mood).status_code == 404


def test_visualize_route_reads_renderer_id(client: TestClient, world: Any) -> None:
    opt = first_option(client, world)
    r = client.post(f"/api/options/{opt['id']}/visualize", json={"renderer_id": "no_such_renderer"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "RENDERER_NOT_FOUND"


# ---- the demo guard ----


def test_demo_mode_blocks_label_edits(
    client: TestClient, item: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    board, item_id = item
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "open sesame")
    monkeypatch.setenv("DEMO_SECRET", "s" * 32)
    offer = {"label": "Mood", "dim_type": "abstract", "kind": "enum"}
    base = f"/api/items/{item_id}"
    attempts = [
        client.post(f"{base}/analyse"),
        client.post(f"{base}/parts", json={"label": "Dial"}),
        client.patch(f"{base}/parts/body", json={"label": "Case"}),
        client.delete(f"{base}/parts/body"),
        client.post(f"{base}/parts/body/extract"),
        client.post(f"{base}/dimensions", json={"label": "W", "type": "abstract", "prompt": "w?"}),
        client.patch(f"{base}/dimensions/subject", json={"label": "Topic"}),
        client.delete(f"{base}/dimensions/subject"),
        client.patch(base, json={"content_type": "ui"}),
        client.post(f"/api/boards/{board}/offers/accept", json=offer),
        client.post(f"/api/boards/{board}/offers/decline", json=offer),
    ]
    reference = client.post(f"{base}/parse")  # an existing mutating route, locked the same way
    assert reference.status_code == 403
    for r in attempts:
        assert r.status_code == reference.status_code, r.request.url
        assert r.json()["error"]["code"] == "DEMO_LOCKED" == reference.json()["error"]["code"]
    # reads stay open, nothing changed
    assert client.get(f"{base}/analysis").status_code == 200
    assert client.get(f"/api/boards/{board}/context").status_code == 200
    body = client.get(f"{base}/analysis").json()
    assert body["content_type"] == "image" and {p["key"] for p in body["parts"]} == {
        "body",
        "detail",
    }
    # position moves are open to the locked visitor, a content type change is not
    assert client.patch(base, json={"x": 5}).status_code == 200
    assert client.post("/api/demo/unlock", json={"passcode": "open sesame"}).status_code == 200
    assert client.patch(base, json={"content_type": "ui"}).status_code == 200


def test_measured_and_legacy_rows_read_as_ai(client: TestClient, item: tuple[str, str]) -> None:
    _board, item_id = item
    with db() as s:
        add_row(s, item_id, "measured_one", source="measured")
        add_row(s, item_id, "typed_one", source="user")
        s.commit()
    dims = {
        d["key"]: d["source"]
        for d in client.get(f"/api/items/{item_id}/analysis").json()["dimensions"]
    }
    assert dims["measured_one"] == "ai" and dims["typed_one"] == "you"
