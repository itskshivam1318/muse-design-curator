import pytest
from sqlalchemy.orm import Session

from app.db.repos import boards
from app.errors import AppError
from app.ingest.common import ItemMeta
from app.ingest.images import ingest_image
from app.ingest.sniff import sniff_image, sniff_video
from tests.media import image_bytes


@pytest.fixture
def board_id(session: Session) -> str:
    return boards.create(session, "b").id


@pytest.mark.parametrize(
    "fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"),
                 ("GIF", "image/gif")]
)  # fmt: skip
def test_accepts_formats_by_magic_bytes(
    session: Session, data_dir, board_id: str, fmt: str, mime: str
) -> None:
    data = image_bytes(fmt, seed=hash(fmt) % 1000)
    assert sniff_image(data)[0] == mime  # type: ignore[index]
    res = ingest_image(session, board_id, data, ItemMeta())
    assert res.item.mime == mime and res.item.kind == "image"


def test_original_stored_byte_for_byte_and_thumb_bounded(
    session: Session, data_dir, board_id: str
) -> None:
    from PIL import Image

    data = image_bytes("PNG", (1200, 800))
    item = ingest_image(session, board_id, data, ItemMeta()).item
    assert (data_dir / item.storage_path).read_bytes() == data
    with Image.open(data_dir / item.thumb_path) as t:
        assert max(t.size) == 512 and t.format == "WEBP"
    assert max(item.w, item.h) == 320


def test_rejects_non_image_and_small_and_mislabelled(
    session: Session, data_dir, board_id: str
) -> None:
    with pytest.raises(AppError) as e:
        ingest_image(session, board_id, b"hello world, not an image", ItemMeta())
    assert e.value.code == "UNSUPPORTED_MEDIA_TYPE"
    with pytest.raises(AppError) as e:
        ingest_image(session, board_id, image_bytes("PNG", (100, 100)), ItemMeta())
    assert e.value.code == "IMAGE_TOO_SMALL"
    with pytest.raises(AppError) as e:
        ingest_image(session, board_id, b"\x89PNG\r\n\x1a\n" + b"garbage", ItemMeta())
    assert e.value.code == "INVALID_IMAGE"


def test_too_large_rejected(
    session: Session, data_dir, board_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1000")
    with pytest.raises(AppError) as e:
        ingest_image(session, board_id, image_bytes("PNG"), ItemMeta())
    assert e.value.code == "FILE_TOO_LARGE"


def test_sha_dedupe_returns_existing(session: Session, data_dir, board_id: str) -> None:
    data = image_bytes()
    a = ingest_image(session, board_id, data, ItemMeta())
    b = ingest_image(session, board_id, data, ItemMeta(origin="extension"))
    assert b.deduped and b.item.id == a.item.id


def test_sniff_video() -> None:
    assert sniff_video(b"\x00\x00\x00\x18ftypmp42")[1] == "mp4"
    assert sniff_video(b"\x00\x00\x00\x14ftypqt  ")[1] == "mov"
    assert sniff_video(b"\x1a\x45\xdf\xa3....")[1] == "webm"
    assert sniff_video(b"nope nope nope") is None


def test_auto_placement_right_of_rightmost(session: Session, data_dir, board_id: str) -> None:
    a = ingest_image(session, board_id, image_bytes(seed=1), ItemMeta(x=100, y=50)).item
    b = ingest_image(session, board_id, image_bytes(seed=2), ItemMeta()).item
    assert (a.x, a.y) == (100, 50)
    assert b.x == a.x + a.w + 24 and b.y == a.y
