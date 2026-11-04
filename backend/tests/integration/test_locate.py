from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.analysis import locate as locate_mod
from app.analysis.locate import locate
from app.api import deps
from app.db.models import BoardItem, ItemPart
from app.db.repos import items as items_repo
from app.errors import AppError
from app.providers.reliability import ModelError
from app.providers.segmentation import MockSegmentationProvider, SegInstance, SegResult
from app.storage import files
from tests.media import image_bytes


class CountingSeg(MockSegmentationProvider):
    def __init__(self) -> None:
        self.calls = 0

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        self.calls += 1
        return super().localize(image, sha256, noun)


class TinySeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        res = super().localize(image, sha256, noun)
        mask = np.zeros_like(res.instances[0].mask)
        mask[0, 0] = True
        return SegResult(True, [SegInstance((0, 0, 1, 1), mask, None)])


class TwoWheelSeg(MockSegmentationProvider):
    """A left and a right instance, the left one scored higher (as SAM does with 'rear wheel')."""

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        w, h = 400, 300
        left = np.zeros((h, w), dtype=bool)
        left[180:270, 40:120] = True
        right = np.zeros((h, w), dtype=bool)
        right[180:270, 260:340] = True
        return SegResult(
            True,
            [
                SegInstance((40, 180, 120, 270), left, 0.9),
                SegInstance((260, 180, 340, 270), right, 0.6),
            ],
        )


class EmptySeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        return SegResult(False, [])


class FailingSeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        raise ModelError("boom")


@pytest.fixture(autouse=True)
def env(data_dir: Path) -> Iterator[None]:
    yield


def setup_item(session: Session, board_id: str, **part: Any) -> str:
    data = image_bytes(seed=1)
    sha = files.sha256_hex(data)
    item = items_repo.create(
        session, board_id=board_id, kind="image", origin="upload", sha256=sha,
        storage_path=files.save_original(data, sha, "png"),
    )  # fmt: skip
    fields = {"key": "body", "label": "Main body", "region_kind": "mask", "source": "ai", **part}
    session.add(ItemPart(item_id=item.id, **fields))
    session.commit()
    return item.id


def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]


def test_box_part_needs_no_model(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_s: Any) -> Any:
        raise AssertionError("no model call expected")

    monkeypatch.setattr(locate_mod, "get_segmentation", boom)
    with deps._factory()() as s:
        item_id = setup_item(s, board(client), region_kind="box", region_json=[0.1, 0.2, 0.5, 0.6])
        r = locate(s, item_id, "body")
    assert (r.kind, r.box, r.mask_url) == ("box", [0.1, 0.2, 0.5, 0.6], None)


def test_mask_located_once_then_cached(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seg = CountingSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        first = locate(s, item_id, "body")
        second = locate(s, item_id, "body")
        part = s.query(ItemPart).filter_by(item_id=item_id).one()
        assert part.mask_path and part.region_kind == "mask"
        assert part.region_json == pytest.approx([0.2, 0.2, 0.8, 0.8], abs=0.02)
    assert seg.calls == 1
    assert first == second and first.kind == "mask"
    assert first.mask_url == f"/api/media/{part.mask_path}"
    assert first.mask_url.startswith("/api/media/masks/")


def test_empty_mask_is_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TinySeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        with pytest.raises(AppError) as e:
            locate(s, item_id, "body")
    assert (e.value.status, e.value.code) == (422, "REGION_EMPTY")


def test_sam_failure_is_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: FailingSeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        with pytest.raises(AppError) as e:
            locate(s, item_id, "body")
    assert (e.value.status, e.value.code) == (502, "REGION_FAILED")


def test_removed_or_unknown_part_is_404(client: TestClient) -> None:
    with deps._factory()() as s:
        item_id = setup_item(s, board(client), removed=True)
        for key in ("body", "nope"):
            with pytest.raises(AppError) as e:
                locate(s, item_id, key)
            assert (e.value.status, e.value.code) == (404, "PART_NOT_FOUND")


def test_missing_mask_file_is_located_again(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seg = CountingSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        first = locate(s, item_id, "body")
        part = s.query(ItemPart).filter_by(item_id=item_id).one()
        assert part.mask_path
        files.abs_path(part.mask_path).unlink()  # the cached file is gone (a wiped volume)
        again = locate(s, item_id, "body")
        assert files.abs_path(part.mask_path).is_file()
    assert seg.calls == 2
    # the located box is its hint now: the same region, found again
    assert again.kind == "mask" and again.box == pytest.approx(first.box, abs=0.01)


def _mask_of(part: ItemPart) -> np.ndarray:
    from PIL import Image

    assert part.mask_path
    with Image.open(files.abs_path(part.mask_path)) as m:
        return np.asarray(m.convert("L")) > 127


def test_hint_picks_the_instance_it_overlaps(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TwoWheelSeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client), region_json=[0.62, 0.58, 0.88, 0.92])
        r = locate(s, item_id, "body")
        part = s.query(ItemPart).filter_by(item_id=item_id).one()
        mask = _mask_of(part)
    assert r.kind == "mask"
    assert mask[220, 300] and not mask[220, 80]  # the right instance, not the higher-scored left
    assert r.box == pytest.approx([0.65, 0.6, 0.85, 0.9], abs=0.01)


def test_hint_far_from_every_instance_falls_back_to_its_box(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TwoWheelSeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client), region_json=[0.3, 0.05, 0.6, 0.3])
        r = locate(s, item_id, "body")
        mask = _mask_of(s.query(ItemPart).filter_by(item_id=item_id).one())
    assert r.box == pytest.approx([0.3, 0.05, 0.6, 0.3], abs=0.01)
    assert mask[50, 180] and not mask[220, 300] and not mask[220, 80]


def test_nothing_found_with_a_hint_uses_the_box(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client), region_json=[0.4, 0.2, 0.7, 0.45])
        r = locate(s, item_id, "body")
        mask = _mask_of(s.query(ItemPart).filter_by(item_id=item_id).one())
    assert r.kind == "mask" and r.box == pytest.approx([0.4, 0.2, 0.7, 0.45], abs=0.01)
    assert mask[100, 220] and not mask[200, 50]


def test_nothing_found_without_a_hint_is_still_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        with pytest.raises(AppError) as e:
            locate(s, item_id, "body")
    assert e.value.code == "REGION_EMPTY"


# ---- the whole object ----


def part_mask(rect: tuple[int, int, int, int]) -> np.ndarray:
    m = np.zeros((300, 400), dtype=bool)
    m[rect[1] : rect[3], rect[0] : rect[2]] = True
    return m


def set_subject(s: Session, item_id: str, subject: str | None) -> None:
    item = s.get(BoardItem, item_id)
    assert item is not None
    item.subject = subject
    s.commit()


class NounSeg(CountingSeg):
    def __init__(self) -> None:
        super().__init__()
        self.nouns: list[str] = []

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        self.nouns.append(noun)
        return super().localize(image, sha256, noun)


def test_locate_object_prompts_sam_with_the_subject(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seg = NounSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        set_subject(s, item_id, "lounge chair")
        locate_mod.locate_object(s, item_id)
    assert seg.nouns == ["lounge chair"]


def test_locate_object_without_subject_needs_analysis_and_skips_sam(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seg = CountingSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        with pytest.raises(AppError) as e:
            locate_mod.locate_object(s, item_id)
    assert (e.value.status, e.value.code) == (422, "NEEDS_ANALYSIS") and seg.calls == 0
    assert e.value.message == "Analyse this item again to find its outline"


def test_locate_object_uses_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seg = CountingSeg()
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: seg)
    with deps._factory()() as s:
        item_id = setup_item(s, board(client))
        set_subject(s, item_id, "lounge chair")
        first = locate_mod.locate_object(s, item_id)
        second = locate_mod.locate_object(s, item_id)
    assert seg.calls == 1
    assert first == second and first.kind == "mask"
    assert first.mask_url and first.mask_url.startswith("/api/media/masks/")


def test_locate_object_falls_back_to_part_union(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = board(client)
    with deps._factory()() as s:
        item_id = setup_item(s, b)
        set_subject(s, item_id, "chair")
        monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: MockSegmentationProvider())
        locate(s, item_id, "body")  # located by the mock: the centre box
        a = part_mask((0, 0, 50, 50))
        rel = "masks/extra.png"
        files.abs_path(rel).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(a.astype(np.uint8) * 255).save(files.abs_path(rel))
        s.add(ItemPart(item_id=item_id, key="top", label="Top", region_kind="mask",
                       source="ai", mask_path=rel))  # fmt: skip
        s.commit()
        body = s.query(ItemPart).filter_by(item_id=item_id, key="body").one()
        with Image.open(files.abs_path(body.mask_path)) as im:
            body_mask = np.asarray(im.convert("L")) > 127
        monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())
        region = locate_mod.locate_object(s, item_id)
    assert region.mask_url
    with Image.open(files.abs_path(region.mask_url.removeprefix("/api/media/"))) as im:
        got = np.asarray(im.convert("L")) > 127
    assert (got == (body_mask | a)).all()


def test_locate_object_empty_raises(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())
    with deps._factory()() as s:
        item_id = setup_item(s, board(client), removed=True)
        set_subject(s, item_id, "chair")
        with pytest.raises(AppError) as e:
            locate_mod.locate_object(s, item_id)
    assert (e.value.status, e.value.code) == (422, "REGION_EMPTY")
