"""The MCP endpoint at /mcp, driven with raw JSON-RPC POSTs (streamable HTTP, handshake era)."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

PROTOCOL = "2025-06-18"
ACCEPT = "application/json, text/event-stream"


class McpSession:
    """One MCP session over the TestClient: initialize on construction, then `call`."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.next_id = 0
        response = self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )
        assert response.status_code == 200, response.text
        self.session_id = response.headers["mcp-session-id"]
        notified = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._headers(),
        )
        assert notified.status_code == 202, notified.text

    def _headers(self) -> dict[str, str]:
        headers = {"accept": ACCEPT, "mcp-protocol-version": PROTOCOL}
        if getattr(self, "session_id", None):
            headers["mcp-session-id"] = self.session_id
        return headers

    def _post(self, method: str, params: dict[str, Any]) -> Any:
        self.next_id += 1
        body = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        return self.client.post("/mcp", json=body, headers=self._headers())

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._post(method, params or {})
        assert response.status_code == 200, response.text
        message = _message(response.headers["content-type"], response.text)
        assert "error" not in message, message
        return message["result"]  # type: ignore[no-any-return]

    def tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = self.call("tools/call", {"name": name, "arguments": args})
        assert result.get("isError") is not True
        [block] = result["content"]
        assert block["type"] == "text"
        return json.loads(block["text"])  # type: ignore[no-any-return]


def _message(content_type: str, text: str) -> dict[str, Any]:
    if content_type.startswith("text/event-stream"):
        data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        return json.loads(data[-1])  # type: ignore[no-any-return]
    return json.loads(text)  # type: ignore[no-any-return]


@pytest.fixture
def mcp_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "1")


def test_mcp_disabled_404(client: TestClient) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = client.post("/mcp", json=body, headers={"accept": ACCEPT})
    assert response.status_code == 404
    assert client.get("/mcp", headers={"accept": "text/event-stream"}).status_code == 404


def test_mcp_lists_tools(client: TestClient, mcp_on: None) -> None:
    listed = McpSession(client).call("tools/list")
    tools = {t["name"]: t for t in listed["tools"]}
    assert {"create_board", "upload_reference", "finish"} <= tools.keys()
    for tool in tools.values():
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert "say" in tool["inputSchema"]["properties"], tool["name"]
        assert "highlight" in tool["inputSchema"]["properties"], tool["name"]


def test_mcp_call_creates_board_and_note_in_one_session(
    client: TestClient, mcp_on: None
) -> None:
    session = McpSession(client)
    created = session.tool("create_board", {"title": "Over MCP", "say": "Starting a board."})
    board_id = created["board_id"]
    note = session.tool("add_note", {"text": "a low oak bench"})
    assert note["item_ids"] == [note["item_id"]]
    items = client.get(f"/api/boards/{board_id}/items").json()["items"]
    assert [i["id"] for i in items] == [note["item_id"]]


def test_mcp_refusal_is_a_readable_result(client: TestClient, mcp_on: None) -> None:
    refused = McpSession(client).tool("add_note", {"text": "no board yet"})
    assert refused["error"] == "NO_BOARD_OPEN"


def test_mcp_sessions_are_separate(client: TestClient, mcp_on: None) -> None:
    first, second = McpSession(client), McpSession(client)
    assert first.session_id != second.session_id
    first.tool("create_board", {"title": "First"})
    assert second.tool("add_note", {"text": "where?"})["error"] == "NO_BOARD_OPEN"
    assert "item_id" in first.tool("add_note", {"text": "here"})


def test_mcp_delete_ends_the_session(client: TestClient, mcp_on: None) -> None:
    from app.main import mcp

    session = McpSession(client)
    session.tool("create_board", {"title": "Short-lived"})
    held = len(mcp.sessions)
    ended = client.delete("/mcp", headers=session._headers())
    assert ended.status_code == 200
    assert len(mcp.sessions) == held - 1
    gone = session._post("tools/list", {})
    assert gone.status_code == 404


def test_mcp_discover_points_clients_at_sessions(client: TestClient, mcp_on: None) -> None:
    """Clients probe `server/discover` first; only handshake (session) versions are advertised,
    so they fall back to `initialize` and get a session to keep the open board in."""
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    probe = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta}}
    response = client.post(
        "/mcp",
        json=probe,
        headers={
            "accept": ACCEPT,
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": "server/discover",
        },
    )
    message = _message(response.headers.get("content-type", ""), response.text)
    assert "2026-07-28" not in message["result"]["supportedVersions"], message
    assert PROTOCOL in message["result"]["supportedVersions"]
