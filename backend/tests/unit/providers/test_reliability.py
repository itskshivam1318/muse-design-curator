import pytest

from app.providers import reliability as rel
from app.providers.reliability import ModelError, with_retry, with_timeout


def test_retries_only_transient_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(rel.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ModelError("MODEL_UNAVAILABLE")
        return "ok"

    assert with_retry(flaky, max_retries=2, base_delay=0.25) == "ok"
    assert sleeps == [0.25, 0.5]


def test_retry_after_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(rel.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def f() -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ModelError("MODEL_RATE_LIMITED", retry_after=1.0)
        return 1

    assert with_retry(f, max_retries=2) == 1
    assert sleeps == [1.0]


@pytest.mark.parametrize("code", ["MODEL_INVALID_RESPONSE", "BILLING_NOT_CONFIGURED",
                                  "PAYLOAD_TOO_LARGE"])  # fmt: skip
def test_never_retries_permanent_codes(code: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rel.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def f() -> None:
        calls["n"] += 1
        raise ModelError(code)

    with pytest.raises(ModelError) as ei:
        with_retry(f, max_retries=3)
    assert ei.value.code == code and calls["n"] == 1


def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rel.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def f() -> None:
        calls["n"] += 1
        raise ModelError("MODEL_TIMEOUT")

    with pytest.raises(ModelError):
        with_retry(f, max_retries=2)
    assert calls["n"] == 3


def test_with_timeout_raises_model_timeout() -> None:
    import time as t

    with pytest.raises(ModelError) as ei:
        with_timeout(lambda: t.sleep(0.5), 0.05)
    assert ei.value.code == "MODEL_TIMEOUT"
    assert with_timeout(lambda: 7, 1) == 7


def test_gateway_timeout_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(rel.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def flaky() -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ModelError("GATEWAY_TIMEOUT")
        return 7

    assert with_retry(flaky, max_retries=3) == 7
    assert sleeps == [rel.GATEWAY_RETRY_DELAY]

    calls["n"] = 0

    def down() -> None:
        calls["n"] += 1
        raise ModelError("GATEWAY_TIMEOUT")

    with pytest.raises(ModelError):
        with_retry(down, max_retries=3)
    assert calls["n"] == 2  # once more, not max_retries more: each try waits the gateway out


def test_gateway_timeout_not_retried_without_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rel.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def down() -> None:
        calls["n"] += 1
        raise ModelError("GATEWAY_TIMEOUT")

    with pytest.raises(ModelError):
        with_retry(down, max_retries=0)
    assert calls["n"] == 1


def test_user_message_never_shows_the_provider_payload() -> None:
    raw = "Error code: 504 - {'error': {'message': 'request timed out'}}"
    for code in ("GATEWAY_TIMEOUT", "MODEL_TIMEOUT"):
        text = rel.user_message(ModelError(code, message=raw))
        assert "{" not in text and "took too long" in text
    assert "busy" in rel.user_message(ModelError("MODEL_RATE_LIMITED", message=raw))
    assert "{" not in rel.user_message(ModelError("SOMETHING_NEW", message=raw))
