import json
from pathlib import Path

import pytest

from app.config import Settings
from app.providers import reliability as rel
from app.providers.meta_client import get_client
from app.providers.reasoning import MuseSparkOpenProvider, MuseSparkProvider
from app.providers.reliability import ModelError
from tests.unit.providers.fake_http import FakeApi, response

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "meta"
URL = "https://api.meta.ai/v1/responses"
SCHEMA = {
    "type": "object",
    "properties": {"palette": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["palette", "confidence"],
    "additionalProperties": False,
}
IMG = b"\xff\xd8\xff\xe0fakejpeg"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(rel.time, "sleep", sleeps.append)
    return sleeps


def provider(api: FakeApi) -> MuseSparkProvider:
    client = get_client(Settings(MODEL_API_KEY="k"), http_client=api.http)
    return MuseSparkProvider(client, "muse-spark-1.3", max_retries=2, timeout=5)


def ok_payload():  # type: ignore[no-untyped-def]
    return response(200, json=json.loads((FIX / "spark_schema.json").read_text()))


def test_client_uses_base_url_and_key() -> None:
    c = get_client(Settings(MODEL_API_KEY="abc"))
    assert str(c.base_url).rstrip("/") == "https://api.meta.ai/v1"
    assert c.api_key == "abc"


def test_extract_sends_json_schema_effort_low_store_false(api: FakeApi) -> None:
    route = api.post(URL, ok_payload())
    out = provider(api).extract([IMG], SCHEMA, "describe")
    assert out == {"palette": "warm", "confidence": 0.8}
    body = json.loads(route.last.content)
    assert body["model"] == "muse-spark-1.3"
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "low"}
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"] == SCHEMA and fmt["strict"] is True
    parts = body["input"][0]["content"]
    assert parts[0] == {"type": "input_text", "text": "describe"}
    assert parts[1]["type"] == "input_image"
    assert parts[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert route.last.headers["authorization"] == "Bearer k"


def test_extract_parses_recorded_payload(api: FakeApi) -> None:
    api.post(URL, ok_payload())
    assert provider(api).extract([IMG], SCHEMA, "p")["palette"] == "warm"


def test_400_schema_error_is_invalid_response_not_retried(api: FakeApi) -> None:
    route = api.post(URL, response(400, json={"error": {"message": "bad schema"}}))
    with pytest.raises(ModelError) as ei:
        provider(api).extract([IMG], SCHEMA, "p")
    assert ei.value.code == "MODEL_INVALID_RESPONSE"
    assert route.call_count == 1


def test_429_retry_after_retried_once_then_succeeds(api: FakeApi, _no_sleep: list[float]) -> None:
    limited = response(429, headers={"Retry-After": "1"}, json={"error": {"message": "slow"}})
    route = api.post(URL, side_effect=[limited, ok_payload()])
    assert provider(api).extract([IMG], SCHEMA, "p")["palette"] == "warm"
    assert route.call_count == 2
    assert _no_sleep == [1.0]


def test_504_is_gateway_timeout_no_retry(api: FakeApi) -> None:
    route = api.post(URL, response(504, json={"error": {}}))
    with pytest.raises(ModelError) as ei:
        provider(api).extract([IMG], SCHEMA, "p")
    assert ei.value.code == "GATEWAY_TIMEOUT"
    assert route.call_count == 1


@pytest.mark.parametrize(
    "status,code", [(413, "PAYLOAD_TOO_LARGE"), (402, "BILLING_NOT_CONFIGURED")]
)
def test_other_status_mapping(api: FakeApi, status: int, code: str) -> None:
    route = api.post(URL, response(status, json={"error": {}}))
    with pytest.raises(ModelError) as ei:
        provider(api).extract([IMG], SCHEMA, "p")
    assert ei.value.code == code and route.call_count == 1


def test_503_retried_then_unavailable(api: FakeApi) -> None:
    route = api.post(URL, response(503, json={"error": {}}))
    with pytest.raises(ModelError) as ei:
        provider(api).extract([IMG], SCHEMA, "p")
    assert ei.value.code == "MODEL_UNAVAILABLE"
    assert route.call_count == 3


def test_non_json_output_is_invalid_response(api: FakeApi) -> None:
    payload = json.loads((FIX / "spark_schema.json").read_text())
    payload["output"][0]["content"][0]["text"] = "not json"
    api.post(URL, response(200, json=payload))
    with pytest.raises(ModelError) as ei:
        provider(api).extract([IMG], SCHEMA, "p")
    assert ei.value.code == "MODEL_INVALID_RESPONSE"


def test_verify_51_images_raises_without_http_call(api: FakeApi) -> None:
    route = api.post(URL, ok_payload())
    with pytest.raises(ModelError) as ei:
        provider(api).verify([IMG] * 51, SCHEMA, "p")
    assert ei.value.code == "TOO_MANY_IMAGES"
    assert route.call_count == 0


def test_extract_over_six_images_rejected(api: FakeApi) -> None:
    route = api.post(URL, ok_payload())
    with pytest.raises(ModelError) as ei:
        provider(api).extract([IMG] * 7, SCHEMA, "p")
    assert ei.value.code == "TOO_MANY_IMAGES" and route.call_count == 0


def test_verify_streams_and_parses(api: FakeApi) -> None:
    text = json.dumps({"palette": "cool", "confidence": 0.7})
    lane = {"item_id": "m", "output_index": 0, "content_index": 0}
    evs = [
        {"type": "response.output_text.delta", "delta": text[:5], **lane},
        {"type": "response.output_text.delta", "delta": text[5:], **lane},
        {"type": "response.output_text.done", "text": text, **lane},
    ]
    sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in evs)
    route = api.post(URL, response(200, headers={"content-type": "text/event-stream"}, text=sse))
    assert provider(api).verify([IMG], SCHEMA, "p") == {"palette": "cool", "confidence": 0.7}
    assert json.loads(route.last.content)["stream"] is True


def test_baseten_provider_retries_once_on_parse_failure(api: FakeApi) -> None:
    def chat(content: str):  # type: ignore[no-untyped-def]
        return response(
            200,
            json={"id": "c", "object": "chat.completion", "created": 0, "model": "m",
                  "choices": [{"index": 0, "finish_reason": "stop",
                               "message": {"role": "assistant", "content": content}}]},
        )  # fmt: skip

    route = api.post(
        "https://inference.baseten.co/v1/chat/completions",
        side_effect=[chat("sorry"), chat('```json\n{"palette": "x", "confidence": 0.5}\n```')],
    )
    p = MuseSparkOpenProvider(
        api_key="b", model="meta-models/muse-spark-open", http_client=api.http
    )
    assert p.extract([IMG], SCHEMA, "p")["palette"] == "x"
    assert route.call_count == 2
