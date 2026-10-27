from fastapi.testclient import TestClient


def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "T"}).json()["id"]


def test_batch_is_stored_and_read_back_newest_first(client: TestClient) -> None:
    bid = board(client)
    events = [
        {"action": "vary.open", "item_id": "itm_1", "at": "2026-10-27T17:47:00Z"},
        {"action": "vary.run", "item_id": "itm_1", "detail": {"target": "markers", "mode": "explore"}},
    ]  # fmt: skip
    assert client.post(f"/api/boards/{bid}/ui-events", json={"events": events}).status_code == 204
    got = client.get(f"/api/boards/{bid}/ui-events").json()
    assert [e["action"] for e in got] == ["vary.run", "vary.open"]
    assert got[0]["detail"] == {"target": "markers", "mode": "explore"}
    assert got[1]["at"] == "2026-10-27T17:47:00Z" and got[1]["item_id"] == "itm_1"


def test_unknown_board_is_404(client: TestClient) -> None:
    r = client.post("/api/boards/brd_nope/ui-events", json={"events": [{"action": "x"}]})
    assert r.status_code == 404


def test_bad_action_oversized_detail_and_big_batches_are_refused(client: TestClient) -> None:
    bid = board(client)
    url = f"/api/boards/{bid}/ui-events"
    assert client.post(url, json={"events": [{"action": "Drop Table"}]}).status_code == 400
    big = {"action": "x", "detail": {"s": "a" * 3000}}
    assert client.post(url, json={"events": [big]}).status_code == 400
    assert client.post(url, json={"events": [{"action": "x"}] * 51}).status_code == 400
    assert client.post(url, json={"events": []}).status_code == 400
    assert client.get(url).json() == []
