"""fal queue client over a mock transport: URLs, auth, statuses, uploads, capped downloads."""

import json

import httpx
import pytest

from app.config import Settings
from app.providers import get_fal
from app.providers.fal import FalClient, MockFal
from app.providers.reliability import ModelError

ENDPOINT = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"


def client(handler: object) -> tuple[FalClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[operator, no-any-return]

    return FalClient("k", http=httpx.Client(transport=httpx.MockTransport(handle))), seen


def test_fal_submit_status_result_headers() -> None:
    def handle(r: httpx.Request) -> httpx.Response:
        if r.method == "POST":
            return httpx.Response(200, json={"request_id": "req-1", "status_url": "x"})
        if r.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "IN_PROGRESS", "logs": []})
        return httpx.Response(200, json={"video": {"url": "https://v3.fal.media/a.mp4"}})

    fal, seen = client(handle)
    assert fal.submit(ENDPOINT, {"prompt": "p", "image_url": "u"}) == "req-1"
    assert fal.status(ENDPOINT, "req-1") == "IN_PROGRESS"
    assert fal.result(ENDPOINT, "req-1") == {"video": {"url": "https://v3.fal.media/a.mp4"}}
    assert all(r.headers["authorization"] == "Key k" for r in seen)
    assert [str(r.url) for r in seen] == [
        f"https://queue.fal.run/{ENDPOINT}",
        # status and result use only owner/app, never the endpoint's subpath
        "https://queue.fal.run/fal-ai/kling-video/requests/req-1/status",
        "https://queue.fal.run/fal-ai/kling-video/requests/req-1",
    ]
    assert json.loads(seen[0].content) == {"prompt": "p", "image_url": "u"}


def test_fal_completed_with_error_is_failed() -> None:
    fal, _ = client(lambda r: httpx.Response(200, json={"status": "COMPLETED", "error": "nsfw"}))
    assert fal.status(ENDPOINT, "req-1") == "FAILED"


def test_fal_http_errors_map_to_model_errors() -> None:
    fal, _ = client(lambda r: httpx.Response(401, json={"detail": "bad key"}))
    with pytest.raises(ModelError) as e:
        fal.submit(ENDPOINT, {})
    assert e.value.code == "PROVIDER_MISCONFIGURED"
    fal, _ = client(lambda r: httpx.Response(503))
    with pytest.raises(ModelError) as e:
        fal.status(ENDPOINT, "req-1")
    assert e.value.code == "MODEL_UNAVAILABLE"


def test_fal_upload_initiates_then_puts() -> None:
    def handle(r: httpx.Request) -> httpx.Response:
        if r.method == "POST":
            return httpx.Response(
                200, json={"upload_url": "https://up.test/put", "file_url": "https://f.test/a"}
            )
        return httpx.Response(200)

    fal, seen = client(handle)
    assert fal.upload(b"png-bytes", "image/png") == "https://f.test/a"
    init, put = seen
    assert str(init.url) == "https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3"
    assert init.headers["authorization"] == "Key k"
    body = json.loads(init.content)
    assert body["content_type"] == "image/png" and body["file_name"].endswith(".png")
    assert put.method == "PUT" and put.content == b"png-bytes"
    assert put.headers["content-type"] == "image/png" and "authorization" not in put.headers


def test_download_over_cap_rejected() -> None:
    fal, seen = client(lambda r: httpx.Response(200, content=b"x" * 2000))
    assert fal.download("https://v3.fal.media/a.glb", 4000) == b"x" * 2000
    assert "authorization" not in seen[0].headers  # the key never leaves fal's API hosts
    with pytest.raises(ModelError) as e:
        fal.download("https://v3.fal.media/a.glb", 1000)
    assert e.value.code == "PAYLOAD_TOO_LARGE"

    def chunked(r: httpx.Request) -> httpx.Response:  # no content-length: counted while read
        return httpx.Response(200, stream=httpx.ByteStream(b"y" * 2000))

    fal, _ = client(chunked)
    with pytest.raises(ModelError) as e:
        fal.download("https://v3.fal.media/a.glb", 1000)
    assert e.value.code == "PAYLOAD_TOO_LARGE"
    with pytest.raises(ModelError):
        fal.download("http://v3.fal.media/a.glb", 4000)
    mock = MockFal(files={"https://f.test/big": b"z" * 10})
    with pytest.raises(ModelError) as e:
        mock.download("https://f.test/big", 5)
    assert e.value.code == "PAYLOAD_TOO_LARGE"


def test_get_fal_mock_and_live() -> None:
    assert isinstance(get_fal(Settings(FAL_PROVIDER="mock")), MockFal)
    assert isinstance(get_fal(Settings(FAL_PROVIDER="fal", FAL_KEY="k")), FalClient)
    with pytest.raises(ModelError) as e:
        get_fal(Settings(FAL_PROVIDER="fal", FAL_KEY=None))
    assert e.value.code == "PROVIDER_MISCONFIGURED"
