from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.db.repos import masks as masks_repo
from app.domain.kinds import ColorSpec, EnumSpec, NumberSpec, OrdinalSpec, ShapeSpec, TextSpec
from app.domain.lens import LensSpec, PartSpec
from app.domain.variation import Nudge, ProtectedSpec, VariationRequest, VariationSpec
from app.providers.reliability import ModelError
from app.retrieval.config import RANKING_CONFIG as CFG
from app.retrieval.filters import SourceItem
from app.retrieval.pool import PoolItem
from app.retrieval.scores import Candidate, Scores
from app.storage import files
from app.validation.comparators import AttrValue
from app.validation.validator import VALIDATOR_VERSION, Providers, validate_shortlist

TARGET = EnumSpec(key="t", label="Strap", category="c", vocabulary=["a", "b", "c"])
PROT = EnumSpec(key="p", label="Finish", category="c", vocabulary=["x", "y"])
PROT_PART = EnumSpec(key="pp", label="Bezel", category="c", vocabulary=["x", "y"], part="case")
TEXT = TextSpec(key="tx", label="Mood", category="c")
COL = ColorSpec(key="col", label="Dial colour", category="c")
ORD = OrdinalSpec(
    key="o", label="Density", category="c", scale=["compact", "regular", "airy", "wide"]
)
SHAPE = ShapeSpec(key="sh", label="Case silhouette", category="c", part="case")
LENS = LensSpec(
    id="demo@1", domain="demo", label="Demo", origin="curated",
    parts=[PartSpec(id="case", sam_prompt="case")],
    attributes=[TARGET, PROT, PROT_PART, TEXT, COL, ORD, SHAPE],
)  # fmt: skip


def av(v, conf=0.9, measured=None):
    return AttrValue(v, conf, "extracted", measured)


def spec(tspec=TARGET, mode="explore", target_value="a", protected=(), nudge=None, values=()):
    req = VariationRequest(
        source_item_id="s", target_key=tspec.key, mode=mode, nudge=nudge,
        target_values=[str(v) for v in values],
    )  # fmt: skip
    prot = tuple(ProtectedSpec(key=s.key, spec=s, value=v) for s, v in protected)
    return VariationSpec(
        request=req, target_spec=tspec, target_value=target_value, values=tuple(values),
        protected=prot,
    )  # fmt: skip


def write_image(name, color):
    p = files.abs_path(f"imgs/{name}.png")
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 300), color).save(p)
    return f"imgs/{name}.png"


def cand(cid, attrs, *, color=(200, 10, 10), prov=("valid", None), lic="CC-BY-4.0", dhash=None):
    item = SimpleNamespace(
        id=cid, sha256=f"sha-{cid}", dhash=dhash, local_path=write_image(cid, color),
        provenance_status=prov[0], provenance_issue=prov[1], license_code=lic, width=300,
        height=300,
    )  # fmt: skip
    pool = PoolItem(item, 0.5, attrs)
    return Candidate(pool, Scores(0, 0, 0, 0, 0))


def source(attrs=None):
    return SourceItem(sha256="sha-src", storage_path=write_image("src", (10, 10, 200)),
                      attrs=attrs or {})  # fmt: skip


def put_mask(session, sha, found=True):
    if not found:
        masks_repo.save(session, sha, "case", found=False, provider="mock")
        return
    m = np.zeros((300, 300), np.uint8)
    m[50:200, 50:200] = 255
    rel = f"masks/{sha}.png"
    p = files.abs_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(m).save(p)
    masks_repo.save(session, sha, "case", found=True, bbox_json=[50, 50, 200, 200],
                    mask_path=rel, score=0.9, provider="mock")  # fmt: skip


class FakeReasoning:
    id, model, is_mock = "fake", "fake", True

    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.calls = answers or [], error, []

    def verify(self, images, schema, prompt):
        self.calls.append((len(images), prompt))
        if self.error:
            raise self.error
        return {"checks": self.answers}

    def extract(self, *a):  # pragma: no cover
        raise AssertionError


class NoSam:
    id, is_mock = "nosam", True

    def localize(self, image, sha, noun):
        raise AssertionError("SAM must not be called when masks are cached")


def run(session, sp, src, cands, reasoning=None, seg=None):
    prov = Providers(reasoning or FakeReasoning(), seg or NoSam())
    return validate_shortlist(session, sp, src, cands, LENS, CFG, prov)


def ans(c, key, answer="same", conf=0.9, steps=None):
    return {"candidate": c, "key": key, "answer": answer, "steps": steps,
            "confidence": conf, "evidence": "looks so"}  # fmt: skip


def test_version():
    assert VALIDATOR_VERSION == "val-3"


def test_validated_only_when_all_pass(session, data_dir):
    sp = spec(protected=[(PROT, "x")])
    src = source({"t": av("a"), "p": av("x")})
    good = cand("good", {"t": av("b"), "p": av("x")})
    bad = cand("bad", {"t": av("b"), "p": av("y")})
    unk = cand("unk", {"t": av("b"), "p": av("x", 0.3)})
    rs = FakeReasoning()
    out = run(session, sp, src, [good, bad, unk], rs)
    assert out["good"].overall == "validated"
    assert {c.check for c in out["good"].checks} == {
        "provenance",
        "duplicate",
        "target",
        "protected",
    }
    assert out["good"].observed_target_value == "b"
    assert out["bad"].overall == "rejected"
    assert out["unk"].overall == "uncertain"
    assert len(rs.calls) == 1  # only the uncertain one reaches verify
    tgt = next(c for c in out["good"].checks if c.check == "target")
    assert tgt.reason == "Strap changed: a → b" and tgt.evidence["source"] == "corpus_index"


def test_mask_found_does_not_upgrade_uncertain(session, data_dir):
    sp = spec(protected=[(PROT_PART, "x")])
    src = source({"t": av("a"), "pp": av("x")})
    c = cand("c1", {"t": av("b"), "pp": av("x", 0.3)})
    put_mask(session, "sha-src")
    put_mask(session, "sha-c1")
    out = run(session, sp, src, [c], FakeReasoning([ans("c1", "pp", "cannot_tell")]))
    assert out["c1"].overall == "uncertain"
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert pc.verdict == "uncertain"


NOTE = "Case not localised; judged on the whole image"


def _part_unfound(session, *, source_found=True, cand_found=False):
    sp = spec(protected=[(PROT_PART, "x")])
    src = source({"t": av("a"), "pp": av("x")})
    c = cand("c1", {"t": av("b"), "pp": av("x")})  # comparator alone would pass
    put_mask(session, "sha-src", found=source_found)
    put_mask(session, "sha-c1", found=cand_found)
    return sp, src, c


def test_part_not_found_is_judged_on_the_whole_image_by_verify(session, data_dir):
    sp, src, c = _part_unfound(session)
    rs = FakeReasoning([ans("c1", "pp", "same")])
    out = run(session, sp, src, [c], rs)
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert pc.verdict == "pass" and out["c1"].overall == "validated"
    assert pc.evidence["source"] == "verify" and pc.evidence["confidence"] == 0.9
    assert NOTE in pc.reason and pc.reason.startswith("Bezel kept (visual check)")
    assert pc.evidence["localisation"] == {
        "part": "case", "not_found_in": ["candidate"], "judged_on": "whole_image",
    }  # fmt: skip
    assert len(rs.calls) == 1
    n_images, prompt = rs.calls[0]
    assert n_images == 2  # the whole source and the whole candidate
    assert "source, whole image" in prompt and "candidate c1, whole image" in prompt


def test_part_not_found_stays_uncertain_without_a_confident_answer(session, data_dir):
    for answers, error in [([ans("c1", "pp", "cannot_tell")], None),
                           ([ans("c1", "pp", "same", 0.6)], None),
                           ([], ModelError("MODEL_TIMEOUT"))]:  # fmt: skip
        sp, src, c = _part_unfound(session)
        out = run(session, sp, src, [c], FakeReasoning(answers, error))
        pc = next(x for x in out["c1"].checks if x.check == "protected")
        assert pc.verdict == "uncertain" and out["c1"].overall == "uncertain", answers
        assert NOTE in pc.reason
    assert "verification unavailable (MODEL_TIMEOUT)" in pc.reason


def test_part_not_found_and_a_confident_change_rejects(session, data_dir):
    sp, src, c = _part_unfound(session)
    out = run(session, sp, src, [c], FakeReasoning([ans("c1", "pp", "different")]))
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert pc.verdict == "fail" and out["c1"].overall == "rejected"
    assert NOTE in pc.reason


def test_source_part_not_found_judges_both_on_the_whole_image(session, data_dir):
    sp, src, _ = _part_unfound(session, source_found=False, cand_found=True)
    c = cand("c1", {"t": av("b"), "pp": av("x", 0.3)})  # unreliable: goes to verify
    rs = FakeReasoning([ans("c1", "pp", "same")])
    out = run(session, sp, src, [c], rs)
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert pc.verdict == "pass" and NOTE in pc.reason
    assert pc.evidence["localisation"]["not_found_in"] == ["source"]
    assert "candidate c1, whole image" in rs.calls[0][1]


def test_text_resolved_only_via_verify(session, data_dir):
    sp = spec(protected=[(TEXT, "calm")])
    src = source({"t": av("a"), "tx": av("calm")})
    c = cand("c1", {"t": av("b"), "tx": av("calm")})
    assert (
        run(session, sp, src, [c], FakeReasoning([ans("c1", "tx", "cannot_tell")]))["c1"].overall
        == "uncertain"
    )
    assert (
        run(session, sp, src, [c], FakeReasoning([ans("c1", "tx", "same", 0.5)]))["c1"].overall
        == "uncertain"
    )
    out = run(session, sp, src, [c], FakeReasoning([ans("c1", "tx", "same", 0.9)]))
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert out["c1"].overall == "validated"
    assert pc.evidence["source"] == "verify" and pc.evidence["confidence"] == 0.9
    assert "looks so" not in pc.reason  # model text lives in evidence only
    out = run(session, sp, src, [c], FakeReasoning([ans("c1", "tx", "different", 0.9)]))
    assert out["c1"].overall == "rejected"


def test_verify_batches_at_most_8_candidates(session, data_dir):
    sp = spec(protected=[(TEXT, "calm")])
    src = source({"t": av("a"), "tx": av("calm")})
    cands = [cand(f"c{i:02d}", {"t": av("b"), "tx": av("calm")}) for i in range(20)]
    rs = FakeReasoning()
    run(session, sp, src, cands, rs)
    assert len(rs.calls) == 3
    for n_images, prompt in rs.calls:
        assert n_images <= 50
    assert [c[0] for c in rs.calls] == [1 + 8, 1 + 8, 1 + 4]


def test_verify_timeout_is_uncertain_with_code(session, data_dir):
    sp = spec(protected=[(TEXT, "calm")])
    src = source({"t": av("a"), "tx": av("calm")})
    c = cand("c1", {"t": av("b"), "tx": av("calm")})
    out = run(session, sp, src, [c], FakeReasoning(error=ModelError("MODEL_TIMEOUT")))
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert pc.verdict == "uncertain"
    assert pc.reason == "verification unavailable (MODEL_TIMEOUT)"
    assert out["c1"].overall == "uncertain"


def test_protected_colour_rejected_with_both_hex(session, data_dir):
    sp = spec(protected=[(COL, "navy")])
    src = source({"t": av("a"), "col": av("navy", 1.0, {"lab": [50, 0, 0], "hex": "#777777"})})
    c = cand("c1", {"t": av("b"), "col": av("red", 0.9, {"lab": [50, 60, 0], "hex": "#C8325A"})})
    out = run(session, sp, src, [c])
    assert out["c1"].overall == "rejected"
    pc = next(x for x in out["c1"].checks if x.check == "protected")
    assert pc.verdict == "fail"
    assert "#777777" in pc.reason and "#C8325A" in pc.reason and "ΔE" in pc.reason
    assert pc.evidence["source"] == "measured"


def test_nudge_needs_direction_and_steps(session, data_dir):
    sp = spec(ORD, "nudge", "compact", nudge=Nudge(direction="more", steps=2))
    src = source({"o": av("compact")})
    exact = cand("exact", {"o": av("airy")})
    short = cand("short", {"o": av("regular")})
    wrong = cand("wrong", {"o": av("compact")})
    out = run(session, sp, src, [exact, short, wrong])
    assert out["exact"].overall == "validated"
    t = next(x for x in out["exact"].checks if x.check == "target")
    assert t.reason == "Density +2 steps: compact → airy"
    assert out["short"].overall == "rejected" and out["wrong"].overall == "rejected"
    # unreliable values go to verify; direction and steps must both match
    for answer, steps, overall in [("more", 2, "validated"), ("more", 1, "rejected"),
                                   ("less", 2, "rejected"), ("same", None, "rejected"),
                                   ("more", None, "uncertain")]:  # fmt: skip
        c = cand("u", {"o": av("airy", 0.3)})
        out = run(session, sp, src, [c], FakeReasoning([ans("u", "o", answer, 0.9, steps)]))
        assert out["u"].overall == overall, (answer, steps)


def test_nudge_less_step_one(session, data_dir):
    sp = spec(ORD, "nudge", "airy", nudge=Nudge(direction="less", steps=1))
    out = run(session, sp, source({"o": av("airy")}), [cand("c", {"o": av("regular")})])
    assert out["c"].overall == "validated"
    t = next(x for x in out["c"].checks if x.check == "target")
    assert t.reason == "Density -1 step: airy → regular"


def test_shape_uncertain_in_band(session, data_dir, monkeypatch):
    monkeypatch.setattr("app.validation.comparators.shape_similarity", lambda a, b: 0.71)
    sp = spec(SHAPE, "explore", "round")
    hu = {"hu": [0.1], "contour": [[0, 0]]}
    src = source({"sh": av("round", 1.0, hu)})
    c = cand("c1", {"sh": av("round", 0.9, hu)})
    put_mask(session, "sha-src")
    put_mask(session, "sha-c1")
    out = run(session, sp, src, [c], FakeReasoning([ans("c1", "sh", "cannot_tell")]))
    t = next(x for x in out["c1"].checks if x.check == "target")
    assert t.verdict == "uncertain"
    assert "Case silhouette similarity 0.71 — too close to call" in t.reason
    assert out["c1"].overall == "uncertain"


def test_invalid_licence_rejected_even_when_attributes_pass(session, data_dir):
    sp = spec(protected=[(PROT, "x")])
    src = source({"t": av("a"), "p": av("x")})
    c = cand("c1", {"t": av("b"), "p": av("x")}, prov=("invalid", "LICENSE_NOT_ALLOWED"),
             lic="CC-BY-NC-2.0")  # fmt: skip
    out = run(session, sp, src, [c])
    assert out["c1"].overall == "rejected"
    pv = next(x for x in out["c1"].checks if x.check == "provenance")
    assert pv.verdict == "fail" and pv.reason == "Licence CC-BY-NC-2.0 is not allowed"


def test_duplicate_of_source_or_earlier_candidate_rejected(session, data_dir):
    sp = spec()
    src = SourceItem(sha256="sha-src", dhash="0" * 16, storage_path=write_image("s2", (1, 2, 3)),
                     attrs={"t": av("a")})  # fmt: skip
    near_src = cand("d1", {"t": av("b")}, dhash="0" * 15 + "1")
    first = cand("d2", {"t": av("b")}, dhash="f" * 16)
    twin = cand("d3", {"t": av("b")}, dhash="f" * 16)
    out = run(session, sp, src, [near_src, first, twin])
    assert out["d1"].overall == "rejected"
    assert out["d2"].overall == "validated"
    assert out["d3"].overall == "rejected"
    assert any(c.check == "duplicate" and c.verdict == "fail" for c in out["d3"].checks)


def test_prefer_and_avoid(session, data_dir):
    src = source({"t": av("a")})
    prefer = spec(TARGET, "prefer", "a", values=("b", "c"))
    avoid = spec(TARGET, "avoid", "a", values=("b",))
    assert run(session, prefer, src, [cand("c", {"t": av("b")})])["c"].overall == "validated"
    assert run(session, prefer, src, [cand("c", {"t": av("a")})])["c"].overall == "rejected"
    assert run(session, avoid, src, [cand("c", {"t": av("c")})])["c"].overall == "validated"
    assert run(session, avoid, src, [cand("c", {"t": av("b")})])["c"].overall == "rejected"


def test_low_confidence_number_nudge_goes_to_verify(session, data_dir):
    num = NumberSpec(key="n", label="Width", category="c", unit="mm", min=0, max=100, tolerance=1)
    sp = spec(num, "nudge", 10, nudge=Nudge(direction="more", steps=1))
    src = source({"n": av(10, 1.0)})
    c = cand("c1", {"n": av(12, 0.3)})  # at the requested position, but unreliable
    rs = FakeReasoning([ans("c1", "n", "cannot_tell")])
    out = run(session, sp, src, [c], rs)
    assert out["c1"].overall == "uncertain"
    assert len(rs.calls) == 1
    ok = run(session, sp, src, [c], FakeReasoning([ans("c1", "n", "more", 0.9, 1)]))
    assert ok["c1"].overall == "validated"
