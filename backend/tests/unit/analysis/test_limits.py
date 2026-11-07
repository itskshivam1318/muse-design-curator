import pytest

from app.analysis.limits import check_and_count, refund
from app.config import Settings
from app.errors import AppError


def test_limit_hits_at_setting() -> None:
    st = Settings(ANALYSE_PER_BOARD_PER_DAY=2)
    check_and_count("b1", "analyse", st)
    check_and_count("b1", "analyse", st)
    with pytest.raises(AppError) as exc:
        check_and_count("b1", "analyse", st)
    assert exc.value.status == 429 and exc.value.code == "DAILY_LIMIT"
    assert exc.value.message == "Daily limit reached for this board, try tomorrow."
    assert exc.value.details["retry_after_s"] > 0


def test_boards_and_kinds_counted_separately() -> None:
    st = Settings(ANALYSE_PER_BOARD_PER_DAY=1, RENDER_PER_BOARD_PER_DAY=1)
    check_and_count("b1", "analyse", st)
    check_and_count("b2", "analyse", st)
    check_and_count("b1", "render", st)
    with pytest.raises(AppError):
        check_and_count("b1", "analyse", st)
    with pytest.raises(AppError):
        check_and_count("b1", "render", st)


def test_refund_frees_slot() -> None:
    st = Settings(RENDER_PER_BOARD_PER_DAY=1)
    check_and_count("b1", "render", st)
    refund("b1", "render")
    check_and_count("b1", "render", st)
    refund("b1", "analyse")  # nothing counted: a no-op


def test_limits_mesh_and_video_kinds() -> None:
    st = Settings(MESH_PER_BOARD_PER_DAY=2, VIDEO_PER_BOARD_PER_DAY=1)
    check_and_count("bm", "mesh", st)
    check_and_count("bm", "mesh", st)
    with pytest.raises(AppError) as exc:
        check_and_count("bm", "mesh", st)
    assert exc.value.status == 429 and exc.value.code == "DAILY_LIMIT"
    refund("bm", "mesh")
    check_and_count("bm", "mesh", st)
    check_and_count("bm", "video", st)
    with pytest.raises(AppError):
        check_and_count("bm", "video", st)
