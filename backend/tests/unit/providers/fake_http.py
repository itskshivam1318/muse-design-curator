"""Tiny respx-style HTTP fake for the openai SDK.

openai>=3 sits on `httpx2`, which respx (httpx-only) cannot patch, so tests hand the SDK a
client whose transport is `httpx2.MockTransport` and route by URL here.
"""

from __future__ import annotations

from typing import Any

import httpx2


class Route:
    def __init__(self, return_value: Any = None, side_effect: list[Any] | None = None) -> None:
        self.return_value = return_value
        self.side_effect = list(side_effect or [])
        self.requests: list[httpx2.Request] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last(self) -> httpx2.Request:
        return self.requests[-1]

    def respond(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        out = self.side_effect.pop(0) if self.side_effect else self.return_value
        if isinstance(out, Exception):
            raise out
        return out  # type: ignore[no-any-return]


class FakeApi:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.http = httpx2.Client(transport=httpx2.MockTransport(self._handle))

    def post(
        self, url: str, return_value: Any = None, side_effect: list[Any] | None = None
    ) -> Route:
        self.routes[url] = Route(return_value, side_effect)
        return self.routes[url]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        route = self.routes.get(str(request.url))
        if route is None:
            raise AssertionError(f"unrouted request {request.method} {request.url}")
        return route.respond(request)


def response(status: int = 200, *, json: Any = None, text: str | None = None,
             headers: dict[str, str] | None = None) -> httpx2.Response:  # fmt: skip
    if text is not None:
        return httpx2.Response(status, text=text, headers=headers)
    return httpx2.Response(status, json=json, headers=headers)
