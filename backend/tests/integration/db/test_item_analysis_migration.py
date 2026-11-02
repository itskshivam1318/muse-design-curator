from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.models import BoardItem, ItemAttribute, ItemPart
from app.db.session import run_migrations


def _attr_row(key: str, part: str | None) -> dict:  # type: ignore[type-arg]
    return {
        "id": f"att_{key}", "item_id": "itm_x", "key": key, "label": key, "category": "c",
        "kind": "text", "part": part, "value_json": "null", "confidence": 0.5,
        "status": "confirmed", "source": "model", "source_detail": "", "enabled": 1,
        "updated_at": "t",
    }  # fmt: skip


@pytest.fixture
def migrated_with_legacy_rows(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    run_migrations(engine, "0007_round2")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO boards (id, title, context, created_at, updated_at) "
                "VALUES ('brd_x', 't', '', 't', 't')"
            )
        )
        item = {
            "id": "itm_x", "board_id": "brd_x", "kind": "image", "origin": "upload",
            "rights_status": "user_supplied", "captured_at": "t", "parse_status": "pending",
            "role": "reference", "x": 0, "y": 0, "w": 0, "h": 0, "z": 0,
            "parse_attempts": 0, "created_at": "t",
        }  # fmt: skip
        c.execute(
            text(
                f"INSERT INTO board_items ({', '.join(item)}) "
                f"VALUES ({', '.join(':' + k for k in item)})"
            ),
            item,
        )
        for key, part in (("hand_style", "hands"), ("overall", None)):
            row = _attr_row(key, part)
            c.execute(
                text(
                    f"INSERT INTO item_attributes ({', '.join(row)}) "
                    f"VALUES ({', '.join(':' + k for k in row)})"
                ),
                row,
            )
    run_migrations(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_backfill_types_and_parts(migrated_with_legacy_rows: Session) -> None:
    s = migrated_with_legacy_rows

    def attr(key: str) -> ItemAttribute:
        return s.scalars(select(ItemAttribute).where(ItemAttribute.key == key)).one()

    assert attr("hand_style").dim_type == "physical"
    assert attr("overall").dim_type == "abstract"
    assert attr("hand_style").removed is False
    parts = s.scalars(select(ItemPart)).all()
    assert [(p.key, p.label, p.region_kind, p.source) for p in parts] == [
        ("hands", "Hands", "mask", "ai")
    ]
    assert s.get(BoardItem, "itm_x").content_type == "image"  # type: ignore[union-attr]
