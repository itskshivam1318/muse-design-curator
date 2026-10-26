import itertools

import pytest
from sqlalchemy.orm import Session

from app.db.repos import boards
from app.db.repos import items as items_repo
from app.errors import AppError
from app.imaging import dhash, hamming
from app.ingest.common import ItemMeta
from app.ingest.video import ingest_video
from tests.media import video_bytes


@pytest.fixture
def board_id(session: Session) -> str:
    return boards.create(session, "b").id


def test_mp4_yields_frames_middle_chosen(session: Session, data_dir, board_id: str) -> None:
    data = video_bytes([0, 1, 2, 3])
    item = ingest_video(session, board_id, data, ItemMeta()).item
    frames = items_repo.frames(session, item.id)
    assert 1 <= len(frames) <= 6 and len(frames) >= 3
    chosen = [f for f in frames if f.chosen]
    assert len(chosen) == 1 and chosen[0].id == frames[len(frames) // 2].id
    assert all(b.t_ms - a.t_ms >= 1000 for a, b in itertools.pairwise(frames))
    assert item.kind == "video" and item.mime == "video/mp4"
    assert (data_dir / item.storage_path).read_bytes() == data
    assert item.thumb_path and (data_dir / item.thumb_path).exists()
    assert item.parse_status == "pending"


def test_black_segments_dropped(session: Session, data_dir, board_id: str) -> None:
    item = ingest_video(session, board_id, video_bytes([None, 0, None]), ItemMeta()).item
    assert len(items_repo.frames(session, item.id)) == 1


def test_black_video_no_usable_frames(session: Session, data_dir, board_id: str) -> None:
    item = ingest_video(session, board_id, video_bytes([None]), ItemMeta()).item
    assert item.parse_status == "failed" and item.parse_error_code == "NO_USABLE_FRAMES"
    assert items_repo.frames(session, item.id) == []
    assert items_repo.get(session, item.id) is not None


def test_max_six_frames(session: Session, data_dir, board_id: str) -> None:
    item = ingest_video(
        session, board_id, video_bytes([0, 1, 2, 3, 0, 1, 2, 3], seg_seconds=1.5), ItemMeta()
    ).item
    assert len(items_repo.frames(session, item.id)) <= 6


def test_too_long_rejected(
    session: Session, data_dir, board_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_VIDEO_SECONDS", "2")
    with pytest.raises(AppError) as e:
        ingest_video(session, board_id, video_bytes([0, 1]), ItemMeta())
    assert e.value.code == "VIDEO_TOO_LONG"


def test_garbage_rejected(session: Session, data_dir, board_id: str) -> None:
    with pytest.raises(AppError) as e:
        ingest_video(session, board_id, b"\x00\x00\x00\x18ftypmp42" + b"junk" * 50, ItemMeta())
    assert e.value.code == "INVALID_VIDEO"


def test_dhash_identical_zero_distance() -> None:
    from PIL import Image

    im = Image.linear_gradient("L").rotate(90)  # horizontal gradient
    assert hamming(dhash(im), dhash(im.copy())) == 0
    assert hamming(dhash(im), dhash(im.transpose(Image.Transpose.FLIP_LEFT_RIGHT))) > 6


def test_unknown_duration_still_capped_by_timestamp(
    session: Session, data_dir, board_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest import video

    monkeypatch.setattr(video, "probe", lambda data: (0.0, 320, 240))  # container omits duration
    monkeypatch.setenv("MAX_VIDEO_SECONDS", "2")
    with pytest.raises(AppError) as e:
        ingest_video(session, board_id, video_bytes([0, 1, 2]), ItemMeta())
    assert e.value.code == "VIDEO_TOO_LONG"


def test_sampling_retains_no_pixels_and_extracts_only_selected() -> None:
    from app.ingest import video

    data = video_bytes([0, 1, 2, 3, 0, 1, 2, 3], seg_seconds=1.5)
    samples = video.sample_frames(data)
    assert len(samples) > 6
    assert all(not hasattr(s, "image") for s in samples)
    picked = video.select_keyframes(samples)
    assert len(picked) <= 6
    images = video.extract_frames(data, {p.idx for p in picked})
    assert set(images) == {p.idx for p in picked} and len(images) <= 6


def test_oversized_dimensions_rejected(
    session: Session, data_dir, board_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest import video

    monkeypatch.setattr(video, "MAX_DIM", 100)
    with pytest.raises(AppError) as e:
        ingest_video(session, board_id, video_bytes([0]), ItemMeta())
    assert e.value.code == "VIDEO_DIMENSIONS_TOO_LARGE"
