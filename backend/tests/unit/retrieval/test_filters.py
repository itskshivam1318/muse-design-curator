import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app.corpus import hashing
from app.db.models import CorpusItem
from app.domain.kinds import EnumSpec, NumberSpec, OrdinalSpec
from app.domain.variation import ProtectedSpec, VariationRequest, VariationSpec
from app.retrieval.config import RANKING_CONFIG as CFG
from app.retrieval.filters import OnBoard, SourceItem, apply_exclusions
from app.retrieval.pool import PoolItem
from app.validation.comparators import AttrValue

TARGET = EnumSpec(key="t", label="Target", category="c", vocabulary=["a", "b", "c"])
PROT = OrdinalSpec(key="p", label="Prot", category="c", scale=["low", "mid", "high"])


def png(seed: int, size: int = 300) -> bytes:
    img = Image.new("L", (size, size))
    img.putdata([((x * seed) ^ (y * 7)) % 256 for y in range(size) for x in range(size)])
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def make(session: Session, data_dir: Path):
    n = [0]

    def _make(attrs=None, rel=0.5, data=None, write=True, **kw) -> PoolItem:
        n[0] += 1
        data = data or png(n[0] + 2)
        rel_path = f"corpus/{n[0]}.png"
        if write:
            (data_dir / "corpus").mkdir(parents=True, exist_ok=True)
            (data_dir / rel_path).write_bytes(data)
        fields = {
            "domain": "d", "source": "s", "source_id": str(n[0]), "landing_url": "u", "image_url": "i",
            "license_code": "cc0", "attribution_text": "a", "local_path": rel_path,
            "sha256": hashing.sha256(data), "dhash": hashing.dhash(data), "width": 300, "height": 300,
            "indexing_status": "indexed",
        }  # fmt: skip
        fields.update(kw)
        c = CorpusItem(**fields)
        session.add(c)
        session.flush()
        return PoolItem(c, rel, attrs or {})

    return _make


def spec(mode="explore", values=(), protected=()) -> VariationSpec:
    return VariationSpec(
        request=VariationRequest(source_item_id="i", target_key="t", mode=mode),
        target_spec=TARGET, target_value="a", values=tuple(values), protected=tuple(protected),
    )  # fmt: skip


def reasons(ex):
    return {e["item"].item.id: e["reason"] for e in ex}


def test_excludes_source_by_sha256(make) -> None:
    p = make()
    src = SourceItem(sha256=p.item.sha256)
    kept, ex = apply_exclusions([p], spec(), src, CFG)
    assert not kept and ex[0]["reason"] == "source"


def test_excludes_source_by_corpus_item_id(make) -> None:
    p = make()
    _kept, ex = apply_exclusions([p], spec(), SourceItem(corpus_item_id=p.item.id), CFG)
    assert ex[0]["reason"] == "source"


def test_excludes_resized_copy_as_duplicate(make) -> None:
    img = Image.new("RGB", (320, 320))
    img.putdata(
        [(x * 255 // 319, (x + y) % 256, y * 255 // 319) for y in range(320) for x in range(320)]
    )
    out = io.BytesIO()
    img.save(out, "PNG")
    data = out.getvalue()
    small = Image.open(io.BytesIO(data)).resize((280, 280))
    buf = io.BytesIO()
    small.save(buf, "PNG")
    a = make(data=data, rel=0.9)
    b = make(data=buf.getvalue(), rel=0.8)
    kept, ex = apply_exclusions([a, b], spec(), SourceItem(), CFG)
    assert kept == [a] and ex[0]["reason"] == "duplicate" and ex[0]["item"] is b


def test_duplicate_of_source_by_dhash(make) -> None:
    p = make()
    src = SourceItem(sha256="other", dhash=p.item.dhash)
    assert apply_exclusions([p], spec(), src, CFG)[1][0]["reason"] == "duplicate"


def test_missing_file_is_unusable(make) -> None:
    p = make(write=False)
    kept, ex = apply_exclusions([p], spec(), SourceItem(), CFG)
    assert not kept and ex[0]["reason"] == "unusable"


def test_small_and_failed_are_unusable(make) -> None:
    small = make(width=200)
    failed = make(indexing_status="failed")
    _, ex = apply_exclusions([small, failed], spec(), SourceItem(), CFG)
    assert [e["reason"] for e in ex] == ["unusable", "unusable"]


def test_invalid_licence_is_provenance(make) -> None:
    p = make(provenance_status="invalid", provenance_issue="no licence")
    assert apply_exclusions([p], spec(), SourceItem(), CFG)[1][0]["reason"] == "provenance"


def test_invalid_and_missing_file_reports_provenance_first(make) -> None:
    p = make(provenance_status="invalid", write=False)
    assert apply_exclusions([p], spec(), SourceItem(), CFG)[1][0]["reason"] == "provenance"


def test_source_precedes_provenance(make) -> None:
    p = make(provenance_status="invalid")
    ex = apply_exclusions([p], spec(), SourceItem(sha256=p.item.sha256), CFG)[1]
    assert ex[0]["reason"] == "source"


def _prot(value="mid") -> ProtectedSpec:
    return ProtectedSpec(key="p", spec=PROT, value=value)


def test_reliable_ordinal_protected_mismatch_is_hard_constraint(make) -> None:
    p = make({"p": AttrValue("high", 0.9, "extracted")})
    src = SourceItem(attrs={"p": AttrValue("mid", 0.9, "extracted")})
    kept, ex = apply_exclusions([p], spec(protected=[_prot()]), src, CFG)
    assert not kept and ex[0]["reason"] == "hard_constraint"
    assert ex[0]["detail"]["attribute"] == "p"
    assert (ex[0]["detail"]["candidate"], ex[0]["detail"]["source"]) == ("high", "mid")


def test_unknown_protected_not_excluded(make) -> None:
    unsure = make({"p": AttrValue("high", 0.4, "uncertain")})
    absent = make({})
    src = SourceItem(attrs={"p": AttrValue("mid", 0.9, "extracted")})
    kept, ex = apply_exclusions([unsure, absent], spec(protected=[_prot()]), src, CFG)
    assert len(kept) == 2 and not ex


NUM = NumberSpec(key="n", label="Num", category="c", unit="mm", min=0, max=100, tolerance=1.0)


def test_low_confidence_protected_number_is_not_a_hard_constraint(make) -> None:
    far = make({"n": AttrValue(44.0, 0.1, "uncertain")})
    src = SourceItem(attrs={"n": AttrValue(36.0, 0.1, "uncertain")})
    prot = ProtectedSpec(key="n", spec=NUM, value=36.0)
    kept, ex = apply_exclusions([far], spec(protected=[prot]), src, CFG)
    assert kept == [far] and not ex


def test_low_confidence_number_target_is_not_no_target_change(make) -> None:
    tnum = VariationSpec(
        request=VariationRequest(source_item_id="i", target_key="n", mode="explore"),
        target_spec=NUM, target_value=40.0, values=(), protected=(),
    )  # fmt: skip
    same = make({"n": AttrValue(40.0, 0.1, "uncertain")})
    src = SourceItem(attrs={"n": AttrValue(40.5, 0.1, "uncertain")})
    kept, ex = apply_exclusions([same], tnum, src, CFG)
    assert kept == [same] and not ex


def test_avoided_value(make) -> None:
    hit = make({"t": AttrValue("b", 0.9, "extracted")})
    ok = make({"t": AttrValue("c", 0.9, "extracted")})
    kept, ex = apply_exclusions([hit, ok], spec("avoid", ["b"]), SourceItem(), CFG)
    assert kept == [ok] and ex[0]["reason"] == "avoided_value" and ex[0]["detail"]["avoided"] == "b"


def test_explore_no_target_change(make) -> None:
    same = make({"t": AttrValue("a", 0.9, "extracted")})
    diff = make({"t": AttrValue("b", 0.9, "extracted")})
    unk = make({})
    src = SourceItem(attrs={"t": AttrValue("a", 0.9, "extracted")})
    kept, ex = apply_exclusions([same, diff, unk], spec("explore"), src, CFG)
    assert kept == [diff, unk] and ex[0]["reason"] == "no_target_change"
    assert ex[0]["detail"]["candidate"] == "a"


def test_prefer_mode_does_not_apply_no_target_change(make) -> None:
    same = make({"t": AttrValue("a", 0.9, "extracted")})
    kept, _ = apply_exclusions([same], spec("prefer", ["b"]), SourceItem(), CFG)
    assert kept == [same]


def test_excludes_corpus_item_already_on_the_board_by_corpus_item_id(make) -> None:
    p = make()
    ob = OnBoard(frozenset({p.item.id}), frozenset(), {p.item.id: "item_b1"})
    kept, ex = apply_exclusions([p], spec(), SourceItem(), CFG, on_board=ob)
    assert not kept and ex[0]["reason"] == "on_board"
    assert ex[0]["detail"] == {"board_item_id": "item_b1"}


def test_excludes_corpus_item_already_on_the_board_by_sha256(make) -> None:
    p = make()
    ob = OnBoard(frozenset(), frozenset({p.item.sha256}), {p.item.sha256: "item_b2"})
    kept, ex = apply_exclusions([p], spec(), SourceItem(), CFG, on_board=ob)
    assert not kept and ex[0]["reason"] == "on_board"
    assert ex[0]["detail"] == {"board_item_id": "item_b2"}


def test_removed_board_items_do_not_exclude(make) -> None:
    p = make()
    kept, ex = apply_exclusions([p], spec(), SourceItem(), CFG, on_board=OnBoard())
    assert kept == [p] and not ex


def test_source_exclusion_still_wins_over_on_board_for_the_source_item(make) -> None:
    p = make()
    ob = OnBoard(frozenset({p.item.id}), frozenset({p.item.sha256}))
    _kept, ex = apply_exclusions(
        [p], spec(), SourceItem(corpus_item_id=p.item.id), CFG, on_board=ob
    )
    assert ex[0]["reason"] == "source"
