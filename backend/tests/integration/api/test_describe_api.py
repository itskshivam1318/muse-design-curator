"""POST /api/nodes/{id}/describe: a suggested direction from the start frame."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import demo
from app.providers.reliability import ModelError
from tests.integration.api.test_nodes_api import add_plugin, make_node, upload_image


@pytest.fixture(autouse=True)
def fal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "k")


@pytest.fixture
def node(client: TestClient) -> tuple[str, str, str]:
    board = client.post("/api/boards", json={"title": "B"}).json()["id"]
    add_plugin(client, board, "video")
    src = upload_image(client, board)
    return board, src, make_node(client, board, "video", [src])["id"]


def renders(board: str) -> int:
    return len(demo.windows._hits.get(f"render:{board}", ()))


class Spy:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.calls = fail, []  # type: list[Any]

    def structured(self, images: list[bytes], schema: dict[str, Any], prompt: str) -> Any:
        self.calls.append((images, schema, prompt))
        if self.fail:
            raise ModelError("MODEL_UNAVAILABLE")
        return {"prompt": "Slow dolly in as the curtain stirs."}


def test_describe_returns_prompt_and_counts_render(
    client: TestClient, node: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    board, _src, nid = node
    spy = Spy()
    monkeypatch.setattr("app.providers.get_reasoning", lambda _s: spy)
    r = client.post(f"/api/nodes/{nid}/describe")
    assert r.status_code == 200, r.text
    assert r.json() == {"prompt": "Slow dolly in as the curtain stirs."}
    assert len(spy.calls) == 1 and len(spy.calls[0][0]) == 1
    assert renders(board) == 1


def test_describe_mock_provider_gives_text(client: TestClient, node: tuple[str, str, str]) -> None:
    r = client.post(f"/api/nodes/{node[2]}/describe")
    assert r.status_code == 200 and isinstance(r.json()["prompt"], str) and r.json()["prompt"]


def test_describe_refunds_on_failure(
    client: TestClient, node: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    board, _, nid = node
    monkeypatch.setattr("app.providers.get_reasoning", lambda _s: Spy(fail=True))
    r = client.post(f"/api/nodes/{nid}/describe")
    assert r.status_code == 502, r.text
    assert renders(board) == 0


def test_describe_bad_frame_takes_no_slot(client: TestClient, node: tuple[str, str, str]) -> None:
    board, _, nid = node
    client.patch(f"/api/nodes/{nid}", json={"params": {"start": "item_nope"}})
    r = client.post(f"/api/nodes/{nid}/describe")
    assert r.status_code == 400 and r.json()["error"]["code"] == "PLUGIN_BAD_INPUT"
    assert renders(board) == 0


def test_describe_locked_in_demo(
    client: TestClient, node: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    board, _, nid = node
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_PASSCODE", "p")
    monkeypatch.setenv("DEMO_SECRET", "s")
    r = client.post(f"/api/nodes/{nid}/describe")
    assert r.status_code == 403 and r.json()["error"]["code"] == "DEMO_LOCKED"
    assert renders(board) == 0


def test_describe_refunds_on_unexpected_error(
    client: TestClient, node: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Boom:
        def structured(self, *_a: Any) -> Any:
            raise RuntimeError("boom")

    board, _, nid = node
    monkeypatch.setattr("app.providers.get_reasoning", lambda _s: Boom())
    with pytest.raises(RuntimeError):
        client.post(f"/api/nodes/{nid}/describe")
    assert renders(board) == 0
