"""Verify batches and SAM calls run concurrently (bounded) with unchanged counts and results."""

import threading
import time
from typing import Any

import pytest

from app.domain.kinds import EnumSpec
from app.domain.lens import LensSpec, PartSpec
from app.providers.segmentation import MockSegmentationProvider, SegResult
from app.retrieval.config import RANKING_CONFIG as CFG
from app.validation import validator
from app.validation.validator import Providers, validate_shortlist
from tests.unit.validation.test_validator import (
    PROT_PART,
    TARGET,
    TEXT,
    FakeReasoning,
    ans,
    av,
    cand,
    source,
    spec,
)

PARTS = ["case", "dial", "strap"]
P_CASE = PROT_PART  # part "case"
P_DIAL = EnumSpec(key="pd", label="Dial", category="c", vocabulary=["x", "y"], part="dial")
P_STRAP = EnumSpec(key="ps", label="Strap tone", category="c", vocabulary=["x", "y"], part="strap")
P_FLAT = EnumSpec(key="pf", label="Finish", category="c", vocabulary=["x", "y"], part="flat")
LENS = LensSpec(
    id="demo@1", domain="demo", label="Demo", origin="curated",
    parts=[PartSpec(id=p, sam_prompt=p) for p in PARTS]
    + [PartSpec(id="flat", sam_prompt="flat", grounding="whole_image")],
    attributes=[TARGET, P_CASE, P_DIAL, P_STRAP, P_FLAT, TEXT],
)  # fmt: skip


class Tracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now = self.peak = 0
        self.calls: list[Any] = []

    def enter(self, what: Any) -> None:
        with self.lock:
            self.calls.append(what)
            self.now += 1
            self.peak = max(self.peak, self.now)

    def leave(self) -> None:
        with self.lock:
            self.now -= 1


class SlowSeg:
    """Later calls finish first, so completion order is the reverse of submission order."""

    id, is_mock = "slow", True

    def __init__(self, delay: float = 0.01, missing: str = "strap") -> None:
        self.t, self.delay, self.missing = Tracker(), delay, missing
        self.mock = MockSegmentationProvider()
        self.n = 0

    def localize(self, image: bytes, sha: str, noun: str) -> SegResult:
        with self.t.lock:
            self.n += 1
            k = self.n
        self.t.enter((sha, noun))
        try:
            time.sleep(max(0.0, self.delay * (6 - k % 6)))
            if noun == self.missing:
                return SegResult()
            return self.mock.localize(image, sha, noun)
        finally:
            self.t.leave()


class SlowReasoning(FakeReasoning):
    def __init__(self, answers: list[dict[str, Any]], delays: list[float]) -> None:
        super().__init__(answers)
        self.t, self.delays = Tracker(), delays

    def verify(self, images, schema, prompt):  # type: ignore[no-untyped-def]
        with self.t.lock:
            i = len(self.t.calls)
        self.t.enter(i)
        try:
            time.sleep(self.delays[i] if i < len(self.delays) else 0)
            return super().verify(images, schema, prompt)
        finally:
            self.t.leave()


def _world(n: int = 20):  # type: ignore[no-untyped-def]
    sp = spec(protected=[(P_CASE, "x"), (P_DIAL, "x"), (P_STRAP, "x"), (P_FLAT, "x"),
                         (TEXT, "calm")])  # fmt: skip
    src = source({"t": av("a"), "pp": av("x"), "pd": av("x"), "ps": av("x"), "pf": av("x"),
                  "tx": av("calm")})  # fmt: skip
    cands = [
        cand(f"c{i:02d}", {"t": av("b"), "pp": av("x", 0.3), "pd": av("x"), "ps": av("x"),
                           "pf": av("x", 0.3), "tx": av("calm")})
        for i in range(n)
    ]  # fmt: skip
    answers = [
        ans(f"c{i:02d}", key, "same" if i % 3 else "different")
        for i in range(n) for key in ("pp", "pf", "ps", "tx")
    ]  # fmt: skip
    return sp, src, cands, answers


def _flat(out: dict[str, Any]) -> list[Any]:
    return [
        (cid, v.overall, [(c.check, c.attribute_key, c.verdict, c.reason) for c in v.checks])
        for cid, v in out.items()
    ]


def _fresh_session():  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.session import make_engine, run_migrations

    engine = make_engine("sqlite://", poolclass=StaticPool)
    run_migrations(engine)
    return Session(engine)


def test_concurrent_validation_matches_sequential_with_the_same_call_counts(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    sp, src, cands, answers = _world()

    def once(sam_n: int, verify_n: int) -> tuple[Any, SlowSeg, SlowReasoning]:
        monkeypatch.setattr(validator, "SAM_CONCURRENCY", sam_n)
        monkeypatch.setattr(validator, "VERIFY_CONCURRENCY", verify_n)
        seg, rs = SlowSeg(), SlowReasoning(answers, [0.3, 0.05, 0.0])
        with _fresh_session() as s:
            out = validate_shortlist(s, sp, src, cands, LENS, CFG, Providers(rs, seg))
        return out, seg, rs

    seq, seq_seg, seq_rs = once(1, 1)
    par, par_seg, par_rs = once(4, 2)
    assert _flat(par) == _flat(seq)
    assert list(par) == [c.pool.item.id for c in cands]
    # unchanged counts: every (image, part) once, verify once per batch of <= 8 candidates
    assert len(par_seg.t.calls) == len(seq_seg.t.calls) == len(set(seq_seg.t.calls))
    assert sorted(par_seg.t.calls) == sorted(seq_seg.t.calls)
    assert len(par_rs.calls) == len(seq_rs.calls) == 3
    assert sorted(n for n, _ in par_rs.calls) == sorted(n for n, _ in seq_rs.calls)
    # bounded concurrency
    assert seq_seg.t.peak == 1 and seq_rs.t.peak == 1
    assert 1 < par_seg.t.peak <= 4
    assert par_rs.t.peak == 2
    # whole-image and part-less checks never reach SAM
    assert {noun for _, noun in par_seg.t.calls} <= set(PARTS)
    # the strap is never found: those checks fall back to the whole image (fix 2), not SAM again
    strap = next(c for c in par["c01"].checks if c.attribute_key == "ps")
    assert "not localised" in strap.reason


def test_progress_is_reported_as_verify_batches_finish(data_dir) -> None:  # type: ignore[no-untyped-def]
    sp, src, cands, answers = _world()
    seen: list[int] = []
    with _fresh_session() as s:
        out = validate_shortlist(
            s, sp, src, cands, LENS, CFG, Providers(FakeReasoning(answers), SlowSeg(0)),
            on_progress=seen.append,
        )  # fmt: skip
    assert seen == sorted(seen) and seen[-1] == len(out) == 20
    assert len(seen) == 3

