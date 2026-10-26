from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.repos import cache as repo
from app.providers.cache import cache_key, cached_call


class Out(BaseModel):
    a: int


def test_same_key_invokes_fn_once(session: Session) -> None:
    calls = {"n": 0}

    def fn() -> Out:
        calls["n"] += 1
        return Out(a=3)

    parts = ["spark", "m1", "v1", {"b": 2, "a": 1}]
    assert cached_call(session, parts, Out, fn) == Out(a=3)
    assert cached_call(session, ["spark", "m1", "v1", {"a": 1, "b": 2}], Out, fn) == Out(a=3)
    assert calls["n"] == 1
    row = repo.get(session, cache_key(parts))
    assert row is not None and row.response_json == {"a": 3} and row.provider == "spark"
    assert row.model == "m1" and row.prompt_version == "v1"


def test_different_key_calls_again(session: Session) -> None:
    calls = {"n": 0}

    def fn() -> dict:
        calls["n"] += 1
        return {"x": calls["n"]}

    assert cached_call(session, ["p", "m", "v", 1], None, fn) == {"x": 1}
    assert cached_call(session, ["p", "m", "v", 2], None, fn) == {"x": 2}
    assert cached_call(session, ["p", "m", "v", 1], None, fn) == {"x": 1}


def test_invalid_cached_json_is_refetched(session: Session) -> None:
    parts = ["p", "m", "v", "k"]
    repo.put(session, cache_key(parts), "p", "m", "v", {"a": "not-an-int"})
    calls = {"n": 0}

    def fn() -> Out:
        calls["n"] += 1
        return Out(a=9)

    assert cached_call(session, parts, Out, fn) == Out(a=9)
    assert calls["n"] == 1
    assert cached_call(session, parts, Out, fn) == Out(a=9)
    assert calls["n"] == 1
