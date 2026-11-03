import base64

import pytest
import respx
from fastapi.testclient import TestClient

from app import events, jobs
from app.ingest import links
from tests.media import image_bytes, video_bytes


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(links, "resolver", lambda host: ["93.184.216.34"])


@pytest.fixture
def board(client: TestClient) -> str:
    r = client.post("/api/boards", json={"title": "B"})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.fixture
def ext(client: TestClient) -> dict[str, str]:
    code = client.post("/api/extension/pair-code").json()["code"]
    token = client.post("/api/extension/pair", json={"code": code}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def upload(client: TestClient, board: str, files: list[tuple[str, bytes]], **data):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/boards/{board}/items",
        files=[("files[]", (n, b, "application/octet-stream")) for n, b in files],
        data={k: str(v) for k, v in data.items()},
    )


def test_board_crud_and_error_shape(client: TestClient) -> None:
    b = client.post("/api/boards", json={"title": "T", "context": "c", "domain": "d"}).json()
    assert client.get(f"/api/boards/{b['id']}").json()["title"] == "T"
    p = client.patch(f"/api/boards/{b['id']}", json={"title": "N"}).json()
    assert p["title"] == "N" and p["context"] == "c"
    r = client.get("/api/boards/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "BOARD_NOT_FOUND"
    r = client.post("/api/boards", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in r.json()["error"]
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_fifty_files_one_bad(client: TestClient, board: str) -> None:
    files = [(f"f{i}.png", image_bytes(seed=i)) for i in range(49)]
    files.insert(10, ("bad.txt", b"not an image at all"))
    r = upload(client, board, files)
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 50
    assert sum(x["ok"] for x in results) == 49
    bad = next(x for x in results if not x["ok"])
    assert bad["filename"] == "bad.txt" and bad["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert len(client.get(f"/api/boards/{board}/items").json()["items"]) == 49


def test_upload_keeps_page_url(client: TestClient, board: str) -> None:
    r = upload(client, board, [("a.png", image_bytes())], page_url="https://shop.test/a")
    assert r.json()["results"][0]["item"]["page_url"] == "https://shop.test/a"
    r = upload(client, board, [("b.png", image_bytes(seed=1))])
    assert r.json()["results"][0]["item"]["page_url"] is None


def test_all_bad_is_400_and_too_many_files(client: TestClient, board: str) -> None:
    assert upload(client, board, [("a.txt", b"zzzz")]).status_code == 400
    r = upload(client, board, [(f"{i}.txt", b"z") for i in range(51)])
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_same_bytes_upload_and_capture_one_item(
    client: TestClient, board: str, ext: dict[str, str]
) -> None:
    data = image_bytes()
    assert upload(client, board, [("a.png", data)]).status_code == 200
    r = client.post(
        f"/api/boards/{board}/items",
        json={"capture": {"image_b64": base64.b64encode(data).decode(), "kind": "image",
                          "source_url": "https://s.test/a.png", "page_url": "https://s.test/"}},
        headers=ext,
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["deduped"] is True
    assert len(client.get(f"/api/boards/{board}/items").json()["items"]) == 1


def test_capture_provenance_and_invalid(
    client: TestClient, board: str, ext: dict[str, str]
) -> None:
    r = client.post(
        f"/api/boards/{board}/items",
        json={"capture": {"image_b64": base64.b64encode(image_bytes(seed=9)).decode(),
                          "source_url": "https://s.test/a.png", "page_url": "https://s.test/p",
                          "page_title": "P", "creator_handle": "@someone"}},
        headers=ext,
    )  # fmt: skip
    item = r.json()["item"]
    assert item["origin"] == "extension" and item["creator_handle"] == "@someone"
    assert item["page_title"] == "P"
    r = client.post(
        f"/api/boards/{board}/items", json={"capture": {"image_b64": "!!!"}}, headers=ext
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_BASE64"
    r = client.post(f"/api/boards/{board}/items", json={})
    assert r.status_code == 400


def test_capture_frames(client: TestClient, board: str, ext: dict[str, str]) -> None:
    frames = [base64.b64encode(image_bytes(seed=s)).decode() for s in (1, 2, 3)]
    r = client.post(
        f"/api/boards/{board}/items",
        json={"capture": {"frames_b64": frames, "kind": "video", "page_url": "https://s.test/"}},
        headers=ext,
    )
    assert r.status_code == 201 and r.json()["item"]["kind"] == "video"


def test_drop_point_respected_and_auto_place(client: TestClient, board: str) -> None:
    r = upload(client, board, [("a.png", image_bytes(seed=1))], x=500, y=700)
    it = r.json()["results"][0]["item"]
    assert (it["x"], it["y"]) == (500, 700)
    r = upload(client, board, [("b.png", image_bytes(seed=2))])
    it2 = r.json()["results"][0]["item"]
    assert it2["x"] == it["x"] + it["w"] + 24 and it2["y"] == 700


def test_video_upload(client: TestClient, board: str) -> None:
    r = upload(client, board, [("v.mp4", video_bytes([0, 1, 2]))])
    item = r.json()["results"][0]["item"]
    assert item["kind"] == "video" and item["parse_status"] == "pending"


@respx.mock
def test_link_og_image_and_login_wall_and_ssrf(client: TestClient, board: str) -> None:
    respx.get("https://example.com/p").respond(
        200, text='<meta property="og:image" content="https://example.com/i.png">'
    )
    respx.get("https://example.com/i.png").respond(200, content=image_bytes())
    r = client.post(f"/api/boards/{board}/items", json={"url": "https://example.com/p"})
    assert r.status_code == 201
    assert r.json()["item"]["page_url"] == "https://example.com/p"
    respx.get("https://insta.example/x").respond(200, text="<html>login</html>")
    r = client.post(f"/api/boards/{board}/items", json={"url": "https://insta.example/x"})
    assert r.json()["item"]["parse_error_code"] == "LINK_NEEDS_EXTENSION"
    r = client.post(f"/api/boards/{board}/items", json={"url": "http://10.0.0.1/"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "SSRF_BLOCKED"


def test_events_and_parse_enqueue(client: TestClient, board: str) -> None:
    seen: list[str] = []
    jobs.register("analyse_item", lambda item_id: seen.append(item_id))
    try:
        with events.subscribe(board) as sub:
            r = upload(client, board, [("a.png", image_bytes())])
            ev = sub.get(timeout=2)
        item_id = r.json()["results"][0]["item"]["id"]
        assert ev and ev["type"] == "item.added" and ev["data"]["id"] == item_id
        assert seen == [item_id]
    finally:
        jobs._registry.pop("analyse_item", None)


def test_patch_and_delete_item(client: TestClient, board: str) -> None:
    it = upload(client, board, [("v.mp4", video_bytes([0, 1, 2]))]).json()["results"][0]["item"]
    r = client.patch(
        f"/api/items/{it['id']}", json={"x": 5, "y": 6, "z": 3, "role": "counter_example"}
    )
    assert r.status_code == 200 and (r.json()["x"], r.json()["role"]) == (5, "counter_example")
    assert client.patch(f"/api/items/{it['id']}", json={"role": "bogus"}).status_code == 400
    assert (
        client.patch(f"/api/items/{it['id']}", json={"chosen_frame_id": "frm_x"}).status_code == 400
    )
    assert client.delete(f"/api/items/{it['id']}").status_code == 204
    assert client.get(f"/api/boards/{board}/items").json()["items"] == []
    assert client.delete(f"/api/items/{it['id']}").status_code == 404


def test_choosing_a_curated_domain_attaches_its_lens_and_keeps_items_analysed(
    client: TestClient, board: str
) -> None:
    upload(client, board, [(f"f{i}.png", image_bytes(seed=i)) for i in range(2)])
    items = client.get(f"/api/boards/{board}/items").json()["items"]
    assert [i["parse_status"] for i in items] == ["completed", "completed"]  # no lens needed
    b = client.patch(f"/api/boards/{board}", json={"domain": "watch"}).json()
    assert b["lens_id"] is not None
    lens = client.get(f"/api/boards/{board}/lens").json()["lens"]
    assert lens["origin"] == "curated" and lens["status"] == "confirmed"
    items = client.get(f"/api/boards/{board}/items").json()["items"]
    assert all(i["parse_status"] == "completed" for i in items)


def test_changing_the_domain_drops_the_old_lens(client: TestClient, board: str) -> None:
    b = client.patch(f"/api/boards/{board}", json={"domain": "watch"}).json()
    watch_lens = b["lens_id"]
    b = client.patch(f"/api/boards/{board}", json={"domain": "fashion"}).json()
    assert b["lens_id"] not in (None, watch_lens)
    assert client.get(f"/api/boards/{board}/lens").json()["lens"]["domain"] == "fashion"
    # back to Auto: no lens until the items vote for one
    b = client.patch(f"/api/boards/{board}", json={"domain": None}).json()
    assert b["domain"] is None and b["lens_id"] is None
    assert client.get(f"/api/boards/{board}/lens").json()["lens"] is None  # not the old one
    # saving the brief alone leaves the lens as it is
    b = client.patch(f"/api/boards/{board}", json={"domain": "fashion"}).json()
    kept = b["lens_id"]
    assert (
        client.patch(f"/api/boards/{board}", json={"context": "trousers"}).json()["lens_id"] == kept
    )
    assert (
        client.patch(f"/api/boards/{board}", json={"domain": "fashion"}).json()["lens_id"] == kept
    )


def test_upload_over_the_daily_limit_keeps_items_but_fails_them(
    client: TestClient, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYSE_PER_BOARD_PER_DAY", "2")
    seen: list[str] = []
    jobs.register("analyse_item", lambda item_id: seen.append(item_id))
    try:
        files = [(f"f{i}.png", image_bytes(seed=i)) for i in range(4)]
        r = upload(client, board, files)
        assert r.status_code == 200
        items = [x["item"] for x in r.json()["results"]]
        assert [i["parse_status"] for i in items] == ["pending", "pending", "failed", "failed"]
        assert [i["parse_error_code"] for i in items[2:]] == ["DAILY_LIMIT", "DAILY_LIMIT"]
        assert seen == [items[0]["id"], items[1]["id"]]
        # a deduped re-upload costs nothing and is not an error
        again = upload(client, board, [("f0.png", image_bytes(seed=0))])
        assert again.status_code == 200 and again.json()["results"][0]["deduped"] is True
    finally:
        jobs._registry.pop("analyse_item", None)
