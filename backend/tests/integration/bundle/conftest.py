from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import deps
from app.db.models import (
    AgentRun,
    AgentStep,
    BoardItem,
    CorpusItem,
    Exploration,
    ExploreOption,
    ItemAttribute,
    ItemPart,
    Lens,
    UiEvent,
    VariationRun,
)
from app.storage.files import abs_path
from tests.media import image_bytes


@dataclass
class Built:
    id: str
    image_a: str
    image_b: str
    note: str
    chained: str
    options: list[str] = field(default_factory=list)
    run: str = ""


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    """A session on the `client` fixture's database."""
    s = deps._factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def built_board(client: TestClient, db: Session) -> Built:
    """Two images, a note, an item chained to the first image, an exploration with a parent and a
    child option, and an agent run with two steps."""
    board = client.post("/api/boards", json={"title": "Bundle me"}).json()["id"]
    files = [
        ("files[]", (f"{n}.png", image_bytes(seed=s), "image/png")) for n, s in (("a", 1), ("b", 2))
    ]
    up = client.post(f"/api/boards/{board}/items", files=files)
    assert up.status_code in (200, 201), up.text
    ids = [r["item"]["id"] for r in up.json()["results"]]
    note = client.post(f"/api/boards/{board}/notes", json={"text": "hello", "x": 5, "y": 6})
    assert note.status_code == 201, note.text
    note_id = note.json()["id"]

    first = db.get(BoardItem, ids[0])
    assert first is not None
    chained = BoardItem(
        board_id=board,
        kind="image",
        origin="generated",
        rights_status="generated",
        sha256="c" * 64,
        storage_path=first.storage_path,
        thumb_path=first.thumb_path,
        created_at="2000-01-01T00:00:00+00:00",  # sorts before the item it refers to
        parent_item_id=first.id,
        put_source_item_id=first.id,
    )
    db.add(chained)
    db.add(
        ItemAttribute(
            item_id=first.id,
            key="k",
            label="K",
            category="c",
            kind="enum",
            value_json="v",
            confidence=0.9,
            status="confirmed",
            source="ai",
        )
    )
    mask = abs_path("masks/m-1.png")
    mask.parent.mkdir(parents=True, exist_ok=True)
    mask.write_bytes(b"png")
    db.add(
        ItemPart(
            item_id=first.id,
            key="p",
            label="P",
            region_kind="mask",
            region_json=[0, 0, 1, 1],
            source="ai",
            mask_path="masks/m-1.png",
        )
    )
    exp = Exploration(board_id=board, item_id=first.id, key="markers")
    db.add(exp)
    db.flush()
    parent = ExploreOption(exploration_id=exp.id, name="parent")
    db.add(parent)
    db.flush()
    child = ExploreOption(
        exploration_id=exp.id,
        name="child",
        parent_option_id=parent.id,
        created_at="2000-01-01T00:00:00+00:00",
    )
    db.add(child)
    run = AgentRun(board_id=board, source="mcp", goal="g", deliverables_json=["d"])
    db.add(run)
    db.flush()
    for turn in (1, 2):
        db.add(
            AgentStep(
                run_id=run.id,
                board_id=board,
                turn=turn,
                tool="t",
                args_json={},
                item_ids_json=[first.id],
            )
        )
    db.commit()
    return Built(board, ids[0], ids[1], note_id, chained.id, [parent.id, child.id], run.id)


def add_vary_run(db: Session, board_id: str, item_id: str) -> None:
    db.add(
        CorpusItem(
            id="cx_x",
            domain="d",
            source="t",
            source_id="1",
            landing_url="u",
            image_url="u",
            license_code="cc0",
            attribution_text="a",
        )
    )
    db.add(Lens(id="lens_x", domain="d", version=1, origin="o", spec_json={}))
    db.flush()
    db.add(
        VariationRun(
            id="run_x",
            board_id=board_id,
            source_item_id=item_id,
            lens_id="lens_x",
            target_key="k",
            mode="m",
            target_values_json={},
            protected_keys_json=[],
            source_snapshot_json={},
            board_profile_version=1,
            ranking_version="r",
            ranking_config_json={},
            validator_version="v",
            providers_json={},
            idempotency_key="idem",
        )
    )
    db.add(UiEvent(board_id=board_id, action="x"))
    db.commit()
