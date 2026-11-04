"""fal.ai queue client (mesh and video plugins).

REST, per https://fal.ai/docs/model-apis/model-endpoints/queue :
- submit  POST https://queue.fal.run/<endpoint id>            -> {"request_id", "status_url", ...}
- status  GET  https://queue.fal.run/<owner>/<app>/requests/<id>/status
          -> {"status": "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED"}; a failed request is COMPLETED
          with an "error" field (reported here as FAILED)
- result  GET  https://queue.fal.run/<owner>/<app>/requests/<id>
  Status and result use only owner/app (`fal-ai/kling-video`), never the endpoint's subpath
  (that answers 405).
- upload, per https://fal.ai/docs/documentation/model-apis/file-access-controls.md :
  POST https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3
  {"file_name", "content_type"} -> {"upload_url", "file_url"}; then PUT the bytes to upload_url.
Auth on fal's own hosts: `Authorization: Key <FAL_KEY>`. Downloads (fal CDN result files) carry
no key.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

import httpx

from app.providers.reliability import ModelError

QUEUE_URL = "https://queue.fal.run"
UPLOAD_URL = "https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3"
TIMEOUT_S = 60.0
FalStatus = Literal["IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED"]
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4"}


def _app(endpoint: str) -> str:
    """`fal-ai/kling-video/v2.5-turbo/pro/image-to-video` -> `fal-ai/kling-video`."""
    parts = endpoint.strip("/").split("/")
    if len(parts) < 2:
        raise ModelError("PROVIDER_MISCONFIGURED", message=f"bad fal endpoint id {endpoint!r}")
    return "/".join(parts[:2])


def _code(status: int) -> str:
    if status in (401, 403):
        return "PROVIDER_MISCONFIGURED"
    if status == 402:
        return "BILLING_NOT_CONFIGURED"
    if status == 413:
        return "PAYLOAD_TOO_LARGE"
    if status == 429:
        return "MODEL_RATE_LIMITED"
    if status >= 500:
        return "MODEL_UNAVAILABLE"
    return "MODEL_INVALID_RESPONSE"


class FalClient:
    is_mock = False

    def __init__(self, key: str, http: httpx.Client | None = None) -> None:
        self._key = key
        self._http = http or httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Key {self._key}"}

    def _send(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            r = self._http.request(method, url, **kw)
        except httpx.TimeoutException:
            raise ModelError("MODEL_TIMEOUT", message=f"fal {method} timed out") from None
        except httpx.HTTPError as e:
            raise ModelError("MODEL_UNAVAILABLE", message=f"fal {method}: {e}") from None
        if r.status_code >= 400:
            raise ModelError(
                _code(r.status_code), message=f"fal {method} {r.status_code}: {r.text[:300]}"
            )
        return r

    def _json(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        r = self._send(method, url, headers=self._auth(), **kw)
        try:
            body = r.json()
        except ValueError:
            raise ModelError("MODEL_INVALID_RESPONSE", message="fal answered non-JSON") from None
        if not isinstance(body, dict):
            raise ModelError("MODEL_INVALID_RESPONSE", message="fal answered a non-object")
        return body

    def upload(self, data: bytes, mime: str) -> str:
        """Put bytes on fal's CDN; returns the file URL a model input can take."""
        name = f"{uuid.uuid4().hex}.{_EXT.get(mime, 'bin')}"
        body = self._json("POST", UPLOAD_URL, json={"file_name": name, "content_type": mime})
        upload_url, file_url = body.get("upload_url"), body.get("file_url")
        if not isinstance(upload_url, str) or not isinstance(file_url, str):
            raise ModelError("MODEL_INVALID_RESPONSE", message="fal upload answer lacks URLs")
        self._send("PUT", upload_url, content=data, headers={"Content-Type": mime})
        return file_url

    def submit(self, endpoint: str, payload: dict[str, Any]) -> str:
        body = self._json("POST", f"{QUEUE_URL}/{endpoint.strip('/')}", json=payload)
        rid = body.get("request_id")
        if not isinstance(rid, str) or not rid:
            raise ModelError("MODEL_INVALID_RESPONSE", message="fal submit lacks request_id")
        return rid

    def status(self, endpoint: str, request_id: str) -> FalStatus:
        body = self._json("GET", f"{QUEUE_URL}/{_app(endpoint)}/requests/{request_id}/status")
        s = body.get("status")
        if s == "COMPLETED" and body.get("error"):
            return "FAILED"
        if s in ("IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED"):
            return s  # type: ignore[no-any-return]
        raise ModelError("MODEL_INVALID_RESPONSE", message=f"fal status {s!r}")

    def result(self, endpoint: str, request_id: str) -> dict[str, Any]:
        return self._json("GET", f"{QUEUE_URL}/{_app(endpoint)}/requests/{request_id}")

    def download(self, url: str, max_bytes: int) -> bytes:
        """A result file, at most max_bytes (PAYLOAD_TOO_LARGE past it). https only, no key."""
        if not url.startswith("https://"):
            raise ModelError("MODEL_INVALID_RESPONSE", message="fal file URL is not https")
        try:
            with self._http.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise ModelError(_code(r.status_code), message=f"fal file {r.status_code}")
                if r.status_code >= 300:  # redirects are not followed: not the file
                    raise ModelError(
                        "MODEL_INVALID_RESPONSE", message=f"fal file redirect {r.status_code}"
                    )
                size = r.headers.get("content-length")
                if size is not None and size.isdigit() and int(size) > max_bytes:
                    raise ModelError("PAYLOAD_TOO_LARGE", message="fal file over the cap")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise ModelError("PAYLOAD_TOO_LARGE", message="fal file over the cap")
                return bytes(buf)
        except httpx.TimeoutException:
            raise ModelError("MODEL_TIMEOUT", message="fal file download timed out") from None
        except httpx.HTTPError as e:
            raise ModelError("MODEL_UNAVAILABLE", message=f"fal file download: {e}") from None


class MockFal:
    """Offline stand-in. `statuses` is the script `status()` walks through (the last one
    repeats); `results` maps an endpoint to its result dict; `files` maps a URL to bytes.
    `calls` logs (method, args)."""

    is_mock = True

    def __init__(
        self,
        statuses: list[FalStatus] | None = None,
        results: dict[str, dict[str, Any]] | None = None,
        files: dict[str, bytes] | None = None,
    ) -> None:
        self.statuses: list[FalStatus] = list(statuses or ["COMPLETED"])
        self.results = dict(results or {})
        self.files = dict(files or {})
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.submit_error: ModelError | None = None
        self._n = 0

    def count(self, method: str) -> int:
        return sum(1 for m, _ in self.calls if m == method)

    def upload(self, data: bytes, mime: str) -> str:
        self.calls.append(("upload", (len(data), mime)))
        url = f"https://fal.media/mock/{uuid.uuid4().hex}.{_EXT.get(mime, 'bin')}"
        self.files[url] = data
        return url

    def submit(self, endpoint: str, payload: dict[str, Any]) -> str:
        self.calls.append(("submit", (endpoint, payload)))
        if self.submit_error is not None:
            raise self.submit_error
        return f"mock-{uuid.uuid4().hex[:12]}"

    def status(self, endpoint: str, request_id: str) -> FalStatus:
        self.calls.append(("status", (endpoint, request_id)))
        s = self.statuses[min(self._n, len(self.statuses) - 1)]
        self._n += 1
        return s

    def result(self, endpoint: str, request_id: str) -> dict[str, Any]:
        self.calls.append(("result", (endpoint, request_id)))
        return dict(self.results.get(endpoint, {"request_id": request_id}))

    def download(self, url: str, max_bytes: int) -> bytes:
        self.calls.append(("download", (url, max_bytes)))
        data = self.files.get(url, b"mock-file")
        if len(data) > max_bytes:
            raise ModelError("PAYLOAD_TOO_LARGE", message="fal file over the cap")
        return data


__all__ = ["FalClient", "FalStatus", "MockFal"]
