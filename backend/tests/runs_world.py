"""A seeded world for run tests: the fixture corpus indexed (mock providers) and demo boards."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import deps
from app.corpus.indexer import index_corpus
from app.db.repos import items as items_repo
from scripts import seed as seed_script

MANIFEST = Path(__file__).resolve().parent / "fixtures" / "corpus" / "manifest.jsonl"


@pytest.fixture
def world(client: TestClient) -> Iterator[dict[str, Any]]:
    """{'session', 'watch': board_id, 'fashion': board_id, 'items': {board_id: [item_id]}}."""
    from app import jobs
    from app.live import quick_index
    from app.runs import orchestrator

    jobs.register("run_variation", orchestrator.run_variation_job)
    jobs.register("deepen_item", quick_index.deepen_item)
    session: Session = deps._factory()()
    for d in ("watch", "fashion"):
        index_corpus(session, d, MANIFEST)
    session.commit()
    boards = {}
    for spec in seed_script.BOARDS:
        if spec["domain"] in ("watch", "fashion"):
            boards[spec["domain"]] = seed_script.seed_board(session, spec, limit=8)
    session.commit()
    out: dict[str, Any] = {"session": session}
    out["items"] = {}
    for d, b in boards.items():
        out[d] = b.id
        out["items"][b.id] = [i.id for i in items_repo.list_active(session, b.id)]
    yield out
    session.close()
