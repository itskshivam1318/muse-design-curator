import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import demo, jobs
from app.analysis import locate as locate_mod
from app.analysis.extract import Bounds, extract, free_slot
from app.analysis.service import queue_analyse
from app.api import deps
from app.board import profile_hook
from app.db.models import BoardItem, ItemPart
from app.db.repos import items as items_repo
from app.errors import AppError
from app.providers.segmentation import MockSegmentationProvider, SegInstance, SegResult
from app.storage import files
from tests.media import image_bytes


class TinySeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        res = super().localize(image, sha256, noun)
        mask = np.zeros_like(res.instances[0].mask)
        mask[0, 0] = True
        return SegResult(True, [SegInstance((0, 0, 1, 1), mask, None)])


class TriangleSeg(MockSegmentationProvider):
    """A part that fills only the lower-left triangle of its box."""

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        inst = super().localize(image, sha256, noun).instances[0]
        ys, xs = np.nonzero(inst.mask)
        mask = np.zeros_like(inst.mask)
        box = np.tril(np.ones((ys.max() - ys.min() + 1, xs.max() - xs.min() + 1), dtype=bool))
        mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] = box
        return SegResult(True, [SegInstance(inst.bbox, mask, inst.score)])


@pytest.fixture(autouse=True)
def env(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)
    queued: list[str] = []
    monkeypatch.setattr(jobs, "enqueue", lambda _name, **kw: queued.append(kw["item_id"]))
    yield queued


def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "B"}).json()["id"]


def add_image(s: Session, board_id: str, **fields: Any) -> BoardItem:
    data = image_bytes(seed=2)
    sha = files.sha256_hex(data)
    item = items_repo.create(
        session=s, board_id=board_id, kind="image", origin="upload", sha256=sha,
        storage_path=files.save_original(data, sha, "png"), parse_status="completed",
        x=0, y=0, w=320, h=240, **fields,
    )  # fmt: skip
    s.add(ItemPart(item_id=item.id, key="body", label="Main body", region_kind="mask", source="ai"))
    s.commit()
    return item


def box(x: float, y: float, w: float, h: float) -> Bounds:
    return Bounds(x, y, w, h)


def count_items(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(BoardItem)) or 0


def test_extract_mask_gives_rgba_child_beside_source(
    client: TestClient, env: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TriangleSeg())
    with deps._factory()() as s:
        src = add_image(s, board(client))
        child = extract(s, src.id, "body")
        s.commit()
        assert child.parent_item_id == src.id and child.extracted_part == "body"
        assert (child.kind, child.origin, child.rights_status) == (
            "image",
            "generated",
            "user_supplied",
        )
        assert child.x >= src.x + src.w and not child.staged
        with Image.open(files.abs_path(child.storage_path)) as im:  # type: ignore[arg-type]
            assert im.mode == "RGBA"
            alpha = np.asarray(im.getchannel("A"))
            assert im.size == (child.width, child.height)
            assert {0, 255} <= set(np.unique(alpha).tolist())  # the mask became the alpha
    assert env == [child.id]


def test_extract_twice_makes_two_items(client: TestClient) -> None:
    with deps._factory()() as s:
        src = add_image(s, board(client))
        a, b = extract(s, src.id, "body"), extract(s, src.id, "body")
        s.commit()
        assert a.id != b.id and a.sha256 != b.sha256
        assert a.y != b.y or a.x != b.x


def test_extract_box_is_plain_crop(client: TestClient) -> None:
    with deps._factory()() as s:
        src = add_image(s, board(client), rights_status="generated")
        s.add(ItemPart(item_id=src.id, key="door", label="Door", region_kind="box",
                       region_json=[0.25, 0.0, 0.75, 0.5], source="you"))  # fmt: skip
        s.commit()
        child = extract(s, src.id, "door")
        assert child.rights_status == "generated"
        with Image.open(io.BytesIO(files.abs_path(child.storage_path).read_bytes())) as im:  # type: ignore[arg-type]
            assert im.size == (200, 150)
            assert np.asarray(im.getchannel("A")).min() == 255


def test_extract_text_range_makes_note(client: TestClient, env: list[str]) -> None:
    text = "The quick brown fox jumps over the lazy dog and runs away."
    with deps._factory()() as s:
        src = items_repo.create(
            s, board_id=board(client), kind="note", origin="note", note_text=text,
            x=10, y=20, w=220, h=150, rights_status="user_supplied", parse_status="completed",
        )  # fmt: skip
        s.add(ItemPart(item_id=src.id, key="intro", label="Intro", region_kind="text_range",
                       region_json=[0, 26], source="ai"))  # fmt: skip
        s.commit()
        child = extract(s, src.id, "intro")
        s.commit()
        assert child.kind == "note" and child.note_text == text[0:26]
        assert (child.parent_item_id, child.extracted_part) == (src.id, "intro")
        assert child.x >= src.x + src.w
    assert env == [child.id]


def test_free_slot_skips_occupied(client: TestClient) -> None:
    with deps._factory()() as s:
        bid = board(client)
        near = box(0, 0, 100, 100)
        first = free_slot(s, bid, near, (100, 100))
        assert first == (140, 0)
        blocker = items_repo.create(
            s, board_id=bid, kind="note", origin="note", x=first[0], y=first[1], w=100, h=100,
        )  # fmt: skip
        s.commit()
        x, y = free_slot(s, bid, near, (100, 100))
        assert (x, y) == (140, 120)
        assert not (x < blocker.x + blocker.w and blocker.x < x + 100
                    and y < blocker.y + blocker.h and blocker.y < y + 100)  # fmt: skip
        assert free_slot(s, bid, near, (100, 100)) == (x, y)  # deterministic
        blocker.staged = True  # a staged take does not block
        s.commit()
        assert free_slot(s, bid, near, (100, 100)) == first


def test_extract_empty_region_creates_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, env: list[str]
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TinySeg())
    with deps._factory()() as s:
        src = add_image(s, board(client))
        before = count_items(s)
        with pytest.raises(AppError) as e:
            extract(s, src.id, "body")
        s.rollback()
        assert (e.value.status, e.value.code) == (422, "REGION_EMPTY")
        assert count_items(s) == before
    assert env == []


def test_extract_text_range_outside_text_is_empty(client: TestClient) -> None:
    with deps._factory()() as s:
        src = items_repo.create(
            s, board_id=board(client), kind="note", origin="note", note_text="short",
            rights_status="user_supplied", parse_status="completed",
        )  # fmt: skip
        s.add(ItemPart(item_id=src.id, key="gone", label="Gone", region_kind="text_range",
                       region_json=[50, 60], source="ai"))  # fmt: skip
        s.commit()
        before = count_items(s)
        with pytest.raises(AppError) as e:
            extract(s, src.id, "gone")
        assert e.value.code == "REGION_EMPTY" and count_items(s) == before


def used(board_id: str, kind: str = "analyse") -> int:
    return len(demo.windows._hits.get(f"{kind}:{board_id}", ()))


def test_extract_counts_one_slot_and_its_child_analysis_is_free(
    client: TestClient, env: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TriangleSeg())
    with deps._factory()() as s:
        b = board(client)
        src = add_image(s, b)
        child = extract(s, src.id, "body")
        s.commit()
        assert child.id in env and used(b) == 1


def test_extract_region_empty_refunds_the_slot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: TinySeg())
    with deps._factory()() as s:
        b = board(client)
        src = add_image(s, b)
        with pytest.raises(AppError):
            extract(s, src.id, "body")
        s.rollback()
        assert used(b) == 0


def test_queue_analyse_counts_refunds_on_claim_miss_and_skips_when_uncounted(
    client: TestClient,
) -> None:
    with deps._factory()() as s:
        b = board(client)
        item = add_image(s, b)
        assert queue_analyse(s, item.id, count=False) is True
        assert used(b) == 0
        item.parse_status = "processing"
        s.flush()
        assert queue_analyse(s, item.id) is False  # claim missed: the slot is given back
        assert used(b) == 0
        item.parse_status = "completed"
        s.flush()
        assert queue_analyse(s, item.id) is True
        assert used(b) == 1
