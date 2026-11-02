from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.analysis import locate as locate_mod
from app.analysis.locate import locate
from app.api import deps
from app.db.models import ItemPart
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
    assert again.kind == "mask" and again.mask_url == first.mask_url
