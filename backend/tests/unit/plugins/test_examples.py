"""The example plugins in docs/plugins/examples load and run as user plugins."""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import BoardItem
from app.plugins import registry
from tests.integration.api.test_nodes_api import (
    add_plugin,
    make_node,
    make_note,
    run_node,
)

EXAMPLES = Path(__file__).resolve().parents[4] / "docs" / "plugins" / "examples"


@pytest.fixture
def examples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> Iterator[None]:
    target = tmp_path / "plugins"
    shutil.copytree(EXAMPLES, target)
    monkeypatch.setenv("PLUGINS_DIR", str(target))
    r = client.post("/api/plugins/reload").json()
    assert r["skipped"] == [] and {"word-count", "tagline"} <= set(r["loaded"])
    yield
    monkeypatch.delenv("PLUGINS_DIR")
    registry.reload()


def test_examples_load_and_run(examples: None, client: TestClient, board: str, db: Session) -> None:
    add_plugin(client, board, "word-count")
    note = make_note(client, board, "a calm oak chair, low and wide")
    run = run_node(client, make_node(client, board, "word-count", [note])["id"])
    assert run["status"] == "done", run
    (item_id,) = run["output"]["created_item_ids"]
    item = db.get(BoardItem, item_id)
    assert item is not None and item.note_text == "7 words"

    add_plugin(client, board, "tagline")
    run = run_node(client, make_node(client, board, "tagline", [note])["id"])
    assert run["status"] == "done", run
    (item_id,) = run["output"]["created_item_ids"]
    item = db.get(BoardItem, item_id)
    assert item is not None and item.kind == "note" and item.note_text
