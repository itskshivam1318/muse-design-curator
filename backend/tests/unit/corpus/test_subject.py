from app.corpus.subject import ABSENT, PRESENT, subject_status


def test_nothing_extracted_is_unknown() -> None:
    assert subject_status([]) is None


def test_nothing_readable_is_absent() -> None:  # a whale indexed on the watch corpus
    assert subject_status([None] * 14) == ABSENT


def test_quarter_readable_is_the_line() -> None:
    assert subject_status(["a"] * 3 + [None] * 11) == ABSENT  # 3 of 14: the toy watch
    assert subject_status(["a"] * 4 + [None] * 10) == PRESENT


def test_false_and_zero_are_readable_values() -> None:
    assert subject_status([False, 0, None, None]) == PRESENT
