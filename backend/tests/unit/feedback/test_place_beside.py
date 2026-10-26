from app.feedback.service import place_beside

PARENT = (0.0, 0.0, 200.0, 150.0)  # x, y, w, h
SIZE = (200.0, 150.0)
X0 = 224.0  # parent.x + parent.w + 24
STEP = 150.0 + 24.0


def test_free_spot_is_right_of_parent() -> None:
    assert place_beside(PARENT, SIZE, [PARENT]) == (X0, 0.0)


def test_one_collision_moves_down_a_row() -> None:
    taken = [PARENT, (X0, 0.0, 200.0, 150.0)]
    assert place_beside(PARENT, SIZE, taken) == (X0, STEP)


def test_margin_counts_as_collision() -> None:
    # 10 px below the first slot's bottom edge: inside the 16 px margin
    taken = [(X0, 160.0, 200.0, 150.0)]
    assert place_beside(PARENT, SIZE, taken) == (X0, 2 * STEP)


def test_full_column_moves_to_next_column() -> None:
    taken = [(X0, k * STEP, 200.0, 150.0) for k in range(5)]
    assert place_beside(PARENT, SIZE, taken) == (X0 + 200.0 + 24.0, 0.0)


def test_everything_taken_falls_back_to_first_position() -> None:
    taken = [(-1000.0, -1000.0, 10000.0, 10000.0)]
    assert place_beside(PARENT, SIZE, taken) == (X0, 0.0)
