from app.db.models import ItemAttribute
from app.domain.attributes import AttributeRecord
from app.extraction.merge import merge_extraction


def row(key: str, value, status: str = "extracted", enabled: bool = True) -> ItemAttribute:  # type: ignore[no-untyped-def]
    return ItemAttribute(
        item_id="i", key=key, label=key, category="c", kind="text", value_json=value,
        confidence=0.8, status=status, source="model", enabled=enabled,
    )  # fmt: skip


def rec(key: str, value, status: str = "extracted") -> AttributeRecord:  # type: ignore[no-untyped-def]
    return AttributeRecord(
        key=key, label=key, category="c", kind="text", value=value, confidence=0.8,
        status=status, source="model",
    )  # fmt: skip


def test_new_row_is_added_with_extracted_event() -> None:
    rows, events = merge_extraction([], [rec("a", "x")])
    assert rows[0]["key"] == "a" and rows[0]["value_json"] == "x"
    assert events[0]["action"] == "extracted" and events[0]["actor"] == "model"
    assert events[0]["before_json"] is None


def test_unedited_row_is_replaced() -> None:
    rows, events = merge_extraction([row("a", "old")], [rec("a", "new")])
    assert rows[0]["value_json"] == "new" and rows[0]["model_value_json"] is None
    assert [e["action"] for e in events] == ["extracted"]


def test_edited_and_confirmed_keep_value_and_store_model_value() -> None:
    for status in ("edited", "confirmed"):
        rows, events = merge_extraction([row("a", "mine", status)], [rec("a", "new")])
        assert "value_json" not in rows[0] and "status" not in rows[0]
        assert rows[0]["model_value_json"] == "new" and rows[0]["model_confidence"] == 0.8
        assert [e["action"] for e in events] == ["model_suppressed"]


def test_disabled_row_is_kept_disabled() -> None:
    rows, events = merge_extraction([row("a", "old", enabled=False)], [rec("a", "new")])
    assert "enabled" not in rows[0] and "value_json" not in rows[0]
    assert rows[0]["model_value_json"] == "new"
    assert events[0]["action"] == "model_suppressed"


def test_unchanged_replacement_emits_no_event() -> None:
    _rows, events = merge_extraction([row("a", "same")], [rec("a", "same")])
    assert events == []
