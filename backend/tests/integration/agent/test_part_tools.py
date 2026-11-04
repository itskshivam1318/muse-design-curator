"""add_part, remove_part, extract_part, wait_all and update_goal as agent tools."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.agent import tools
from app.agent.context import ToolContext
from app.agent.tools import wait
from app.analysis import locate as locate_mod
from app.api import deps
from app.board import profile_hook
from app.db.models import ItemPart
from app.db.repos import items as items_repo
from app.providers.segmentation import MockSegmentationProvider, SegResult
from app.storage import files
from tests.media import image_bytes


class EmptySeg(MockSegmentationProvider):
    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        return SegResult(False, [])


@pytest.fixture(autouse=True)
def env(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)
    monkeypatch.setattr(jobs, "enqueue", lambda _name, **_kw: None)
    monkeypatch.setattr(wait, "POLL_S", 0.05)
    yield


@pytest.fixture
def item_id(client: TestClient, board: str) -> str:
    data = image_bytes(seed=3)
    sha = files.sha256_hex(data)
    with deps._factory()() as s:
        item = items_repo.create(
            s, board_id=board, kind="image", origin="upload", sha256=sha,
            storage_path=files.save_original(data, sha, "png"), parse_status="completed",
            x=0, y=0, w=320, h=240,
        )  # fmt: skip
        s.add(ItemPart(item_id=item.id, key="body", label="Body", region_kind="mask", source="ai"))
        s.commit()
        return item.id


def part_keys(client: TestClient, item_id: str) -> list[str]:
    return [p["key"] for p in client.get(f"/api/items/{item_id}/analysis").json()["parts"]]


async def test_add_part_returns_region(ctx: ToolContext, item_id: str) -> None:
    res = await tools.run_tool(ctx, "add_part", {"item_id": item_id, "label": "Front wheel"})
    assert "error" not in res, res
    assert res["part"]["key"] == "front_wheel" and res["region"]["kind"] == "mask"
    assert res["item_ids"] == [item_id]


async def test_add_part_with_box_stores_hint(
    ctx: ToolContext, client: TestClient, item_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())  # the hint stands
    box = [0.1, 0.2, 0.5, 0.6]
    res = await tools.run_tool(ctx, "add_part", {"item_id": item_id, "label": "Seat", "box": box})
    assert "error" not in res, res
    assert res["region"]["box"] == pytest.approx(box, abs=0.01)
    parts = client.get(f"/api/items/{item_id}/analysis").json()["parts"]
    assert next(p for p in parts if p["key"] == "seat")["region"] == pytest.approx(box, abs=0.01)


async def test_add_part_bad_box_is_refused(ctx: ToolContext, item_id: str) -> None:
    res = await tools.run_tool(
        ctx, "add_part", {"item_id": item_id, "label": "Seat", "box": [0.5, 0.2, 0.1, 0.6]}
    )
    assert res["error"] == "BAD_BOX"


async def test_add_part_empty_region_removes_part(
    ctx: ToolContext, client: TestClient, item_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locate_mod, "get_segmentation", lambda _s: EmptySeg())
    res = await tools.run_tool(ctx, "add_part", {"item_id": item_id, "label": "Ghost"})
    assert res["error"] == "REGION_EMPTY"
    assert "shorter name" in res["message"]
    assert "ghost" not in part_keys(client, item_id)


async def test_remove_part(ctx: ToolContext, client: TestClient, item_id: str) -> None:
    res = await tools.run_tool(ctx, "remove_part", {"item_id": item_id, "part": "body"})
    assert res == {"removed": "body", "item_ids": [item_id]}
    assert part_keys(client, item_id) == []
    again = await tools.run_tool(ctx, "remove_part", {"item_id": item_id, "part": "body"})
    assert "error" in again


async def test_extract_part_creates_item(
    ctx: ToolContext, client: TestClient, board: str, item_id: str
) -> None:
    res = await tools.run_tool(ctx, "extract_part", {"item_id": item_id, "part": "body"})
    assert "error" not in res, res
    assert res["item_ids"] == [res["item_id"]]
    items = {i["id"]: i for i in client.get(f"/api/boards/{board}/items").json()["items"]}
    assert items[res["item_id"]]["parent_item_id"] == item_id


async def test_wait_all_returns_each(ctx: ToolContext, item_id: str) -> None:
    res = await tools.run_tool(ctx, "wait_all", {"kind": "item", "ids": [item_id, "itm_nope"]})
    assert res["results"][item_id]["state"] == "completed"
    assert res["results"]["itm_nope"]["error"] == "ITEM_NOT_ON_BOARD"
    assert res["item_ids"] == [item_id]


async def test_wait_all_refuses_too_many_ids(ctx: ToolContext) -> None:
    res = await tools.run_tool(
        ctx, "wait_all", {"kind": "item", "ids": [f"i{n}" for n in range(7)]}
    )
    assert res["error"] == "BAD_IDS"


async def test_update_goal_sets_deliverables(ctx: ToolContext) -> None:
    none = await tools.run_tool(ctx, "update_goal", {"goal": "x"})
    assert none["error"] == "NO_RUN"
    await tools.run_tool(ctx, "set_goal", {"goal": "old", "deliverables": ["a"]})
    res = await tools.run_tool(ctx, "update_goal", {"deliverables": ["front view", "rear view"]})
    assert res["goal"] == "old" and res["deliverables"] == ["front view", "rear view"]
    res = await tools.run_tool(ctx, "update_goal", {"goal": "new"})
    assert res["goal"] == "new" and res["deliverables"] == ["front view", "rear view"]
    bad = await tools.run_tool(ctx, "update_goal", {"deliverables": ["a", "a"]})
    assert bad["error"] == "BAD_DELIVERABLES"


def test_registry_offers_the_new_tools() -> None:
    names = [d["name"] for d in tools.definitions("muse")]
    for name in ("add_part", "remove_part", "extract_part", "wait_all", "update_goal"):
        assert name in names
