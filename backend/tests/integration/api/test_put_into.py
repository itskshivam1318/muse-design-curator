"""Put into: connect one picture to another on a board to put the first into the second."""

from typing import Any

from fastapi.testclient import TestClient


def board_items(client: TestClient, world: dict[str, Any]) -> list[dict[str, Any]]:
    r = client.get(f"/api/boards/{world['watch']}/items")
    assert r.status_code == 200, r.json()
    body = r.json()
    return body["items"] if isinstance(body, dict) else body  # type: ignore[no-any-return]


def test_items_carry_put_source_item_id(client: TestClient, world: dict[str, Any]) -> None:
    items = board_items(client, world)
    assert items
    assert all(i["put_source_item_id"] is None for i in items)
