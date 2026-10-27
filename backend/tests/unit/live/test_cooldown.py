"""Unreachable live sources cool down in process (403/401/429 at once, timeouts after two)."""

from typing import Any

import httpx
import pytest

from app.live import search
from tests.unit.live.test_search import Fake, mi, run


def http_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://x")
    return httpx.HTTPStatusError(str(code), request=req, response=httpx.Response(code, request=req))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    now = {"t": 1000.0}
    monkeypatch.setattr(search, "_clock", lambda: now["t"])
    return now


def fakes(**errors: Any) -> dict[str, Fake]:
    out = {"commons": Fake("commons", {"*": [mi("commons", "1")]})}
    for name, err in errors.items():
        out[name] = Fake(name, {"*": [mi(name, "2")]}, error=err)
    return out


@pytest.mark.parametrize("code", [401, 403, 429])
def test_auth_and_rate_limit_errors_cool_down_at_once(clock: dict[str, float], code: int) -> None:
    fs = fakes(met=http_error(code))
    first = run(fs)
    assert first.sources["met"].status == "failed"
    assert first.sources["met"].error_code == f"HTTP_{code}"
    calls = len(fs["met"].calls)
    clock["t"] += 899
    again = run(fs)
    assert again.sources["met"].status == "skipped"
    assert again.sources["met"].error_code == "COOLING_DOWN"
    assert len(fs["met"].calls) == calls  # not asked at all
    assert again.sources["commons"].status == "ok" and [i.id for i in again] == ["cx_commons_1"]
    assert again.failed() == []  # skipped is not "failed" in this run
    clock["t"] += 2  # 901 s after the failure
    assert run(fs).sources["met"].status == "failed"  # asked again


def test_other_errors_do_not_cool_down(clock: dict[str, float]) -> None:
    fs = fakes(met=http_error(500))
    for _ in range(3):
        assert run(fs).sources["met"].status == "failed"


def test_timeouts_cool_down_after_two_in_a_row(clock: dict[str, float]) -> None:
    fs = fakes(openverse=httpx.ReadTimeout("slow"))
    assert run(fs).sources["openverse"].error_code == "TIMEOUT"
    fs["openverse"].error = None  # answers once: the streak resets
    assert run(fs).sources["openverse"].status == "ok"
    fs["openverse"].error = httpx.ReadTimeout("slow")
    assert run(fs).sources["openverse"].status == "failed"
    assert run(fs).sources["openverse"].status == "failed"  # second in a row
    assert run(fs).sources["openverse"].status == "skipped"


def test_running_out_of_time_counts_as_a_timeout(clock: dict[str, float]) -> None:
    fs = {"commons": Fake("commons", {"*": [mi("commons", "1")]}),
          "smithsonian": Fake("smithsonian", {"*": [mi("smithsonian", "2")]}, delay=0.5)}  # fmt: skip
    assert run(fs, timeout=0.1).sources["smithsonian"].status == "timeout"
    assert run(fs, timeout=0.1).sources["smithsonian"].status == "timeout"
    out = run(fs, timeout=0.1)
    assert out.sources["smithsonian"].status == "skipped"
    assert out.sources["commons"].status == "ok"


def test_zero_disables_the_cooldown(clock: dict[str, float], monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LIVE_SOURCE_COOLDOWN_S", "0")
    fs = fakes(met=http_error(403))
    for _ in range(3):
        assert run(fs).sources["met"].status == "failed"


def test_default_cooldown_setting() -> None:
    from app.config import Settings

    assert Settings().LIVE_SOURCE_COOLDOWN_S == 900
