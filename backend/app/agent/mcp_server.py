"""The agent tools over MCP (streamable HTTP) at `/mcp`, for Claude Code and other MCP clients.

Each MCP session gets one `ToolContext(source="mcp")`, so the board a session opens (and the run
it starts) carries over to its later calls. The endpoint is always mounted; while `MCP_ENABLED` is
off it answers 404.

The server speaks the session (handshake) era of the protocol only: the stateless 2026-07-28 era
has no session to keep the open board in, so `server/discover` advertises handshake versions and
clients fall back to `initialize`.
"""

import json
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import mcp_types as types
from fastapi import FastAPI
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from app.agent import tools
from app.agent.context import ApiClient, ToolContext
from app.config import Settings, get_settings

log = logging.getLogger(__name__)

MAX_SESSIONS = 256  # sessions open at once (more get 503) and contexts kept (LRU dropped past)


class Sessions:
    """One `ToolContext` per MCP session id, least recently used dropped past `MAX_SESSIONS`."""

    def __init__(self, limit: int = MAX_SESSIONS) -> None:
        self._limit = limit
        self._contexts: OrderedDict[str, ToolContext] = OrderedDict()

    async def get(self, session_id: str) -> ToolContext:
        ctx = self._contexts.get(session_id)
        if ctx is None:
            ctx = self._contexts[session_id] = _new_context()
        self._contexts.move_to_end(session_id)
        while len(self._contexts) > self._limit:
            _, evicted = self._contexts.popitem(last=False)
            await evicted.api.aclose()
        return ctx

    async def drop(self, session_id: str) -> None:
        ctx = self._contexts.pop(session_id, None)
        if ctx is not None:
            await ctx.api.aclose()

    async def close(self) -> None:
        for session_id in list(self._contexts):
            await self.drop(session_id)

    def __len__(self) -> int:
        return len(self._contexts)


def _new_context() -> ToolContext:
    return ToolContext(api=ApiClient(), board_id=None, run_id=None, source="mcp")


def _session_id(ctx: ServerRequestContext[Any, Any]) -> str | None:
    request = ctx.request
    if isinstance(request, Request):
        return request.headers.get(MCP_SESSION_ID_HEADER)
    return None


def build_mcp(sessions: Sessions) -> Server[Any]:
    """The MCP server: every tool `definitions("mcp")` offers, run against the caller's session."""

    async def list_tools(
        _ctx: ServerRequestContext[Any, Any], _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=d["name"], description=d["description"], input_schema=d["parameters"]
                )
                for d in tools.definitions("mcp")
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        session_id = _session_id(ctx)
        if session_id is None:  # no session to keep a board in: this call stands alone
            tool_ctx = _new_context()
            try:
                result = await tools.run_tool(tool_ctx, params.name, params.arguments)
            finally:
                await tool_ctx.api.aclose()
        else:
            tool_ctx = await sessions.get(session_id)
            result = await tools.run_tool(tool_ctx, params.name, params.arguments)
        # a refusal is a normal result too: the model reads its {"error", "message"}
        return types.CallToolResult(content=[types.TextContent(text=json.dumps(result))])

    async def discover(
        ctx: ServerRequestContext[Any, Any], _params: types.RequestParams
    ) -> types.DiscoverResult:
        return types.DiscoverResult(
            supported_versions=list(HANDSHAKE_PROTOCOL_VERSIONS),
            capabilities=server.get_capabilities(protocol_version=ctx.protocol_version),
        )

    server: Server[Any] = Server(
        "muse", version="1", on_list_tools=list_tools, on_call_tool=call_tool
    )
    server.add_request_handler("server/discover", types.RequestParams, discover)
    return server


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Only this machine and the app's own public address may reach `/mcp`: a web page on some
    other host (DNS rebinding) must not drive the tools, `upload_reference` reads local files.
    A `name:*` entry matches that name on any port."""
    public = urlsplit(settings.PUBLIC_APP_URL)
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    origins = ["http://localhost", "http://localhost:*", "http://127.0.0.1", "http://127.0.0.1:*"]
    if public.netloc:
        hosts.append(public.netloc)
        origins.append(f"{public.scheme}://{public.netloc}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


class McpEndpoint:
    """The ASGI app at `/mcp`. `run()` (in the app's lifespan) starts a fresh session manager:
    a manager runs only once, and the app's lifespan may run more than once (tests)."""

    def __init__(self) -> None:
        self.sessions = Sessions()
        self._manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        manager = StreamableHTTPSessionManager(
            app=build_mcp(self.sessions),
            json_response=True,
            security_settings=transport_security(get_settings()),
            max_sessions=MAX_SESSIONS,
        )
        async with manager.run():
            self._manager = manager
            try:
                yield
            finally:
                self._manager = None
                await self.sessions.close()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        manager = self._manager
        if scope["type"] != "http" or manager is None or not get_settings().MCP_ENABLED:
            not_found = JSONResponse(
                {"error": {"code": "NOT_FOUND", "message": "Not Found"}}, status_code=404
            )
            await not_found(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)
        if scope["method"] == "DELETE":  # the client ended its session
            session_id = Request(scope).headers.get(MCP_SESSION_ID_HEADER)
            if session_id:
                await self.sessions.drop(session_id)


def mount_mcp(app: FastAPI) -> McpEndpoint:
    """Route `/mcp` to the MCP endpoint; the caller runs `endpoint.run()` in its lifespan."""
    endpoint = McpEndpoint()
    app.add_route("/mcp", endpoint, include_in_schema=False)  # type: ignore[arg-type]
    return endpoint
