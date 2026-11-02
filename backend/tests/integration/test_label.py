from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import jobs
from app.analysis import label, service
from app.analysis.types import Analysis, DimensionOut, PartOut, Region
from app.api import deps
from app.board import profile_hook
from app.db.models import BoardItem, ItemAttribute, ItemPart
from app.db.repos import attributes as attrs_repo
from app.db.repos import items as items_repo
from app.errors import AppError
from app.extraction.service import edit_attribute
from app.storage import files
from tests.media import image_bytes


@pytest.fixture(autouse=True)
def env(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    monkeypatch.setattr(profile_hook, "request_recompute", lambda _board_id: None)
    queued: list[str] = []
    monkeypatch.setattr(jobs, "enqueue", lambda _name, **kw: queued.append(kw["item_id"]))
    yield queued


def make_item(client: TestClient, session: Session) -> BoardItem:
    board_id = client.post("/api/boards", json={"title": "B"}).json()["id"]
    data = image_bytes(seed=3)
    sha = files.sha256_hex(data)
    item = items_repo.create(
        session, board_id=board_id, kind="image", origin="upload", sha256=sha,
        storage_path=files.save_original(data, sha, "png"), parse_status="completed",
    )  # fmt: skip
    session.commit()
    return item


def part_row(session: Session, item_id: str, key: str) -> ItemPart:
    session.expire_all()
    return session.query(ItemPart).filter_by(item_id=item_id, key=key).one()


def attr(session: Session, item_id: str, key: str) -> ItemAttribute:
    session.expire_all()
    return session.query(ItemAttribute).filter_by(item_id=item_id, key=key).one()


def stub_analysis(monkeypatch: pytest.MonkeyPatch, a: Analysis) -> None:
    monkeypatch.setattr(service, "run_analyser", lambda *_a, **_k: a)


def ai_analysis() -> Analysis:
    return Analysis(
        content_type="image", summary="s",
        parts=[PartOut(key="body", label="Body", region_kind="mask")],
        dimensions=[
            DimensionOut(
                key="shape", label="Shape", type="physical", part="body", kind="text",
                value="round", confidence=0.9,
            )
        ],
    )  # fmt: skip


def test_add_part_without_region_is_a_you_mask_part(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        p = label.add_part(s, item.id, "Left Wing", None)
        s.commit()
        assert (p.key, p.source, p.region_kind, p.region_json) == ("left_wing", "you", "mask", None)
        evs = attrs_repo.events(s, item.id, "left_wing")
    assert [(e.actor, e.action) for e in evs] == [("user", "edited")]


def test_add_part_with_box_and_duplicate(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        p = label.add_part(s, item.id, "Door", Region(kind="box", box=[0.1, 0.1, 0.5, 0.5]))
        assert (p.region_kind, p.region_json) == ("box", [0.1, 0.1, 0.5, 0.5])
        with pytest.raises(AppError) as e:
            label.add_part(s, item.id, "door", None)
    assert e.value.code == "PART_EXISTS"


def test_rename_part_keeps_key_and_drops_mask(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        s.add(ItemPart(item_id=item.id, key="body", label="Body", region_kind="mask",
                       mask_path="masks/x.png", source="ai"))  # fmt: skip
        s.commit()
        p = label.rename_part(s, item.id, "body", "Torso")
        s.commit()
        assert (p.key, p.label, p.source, p.mask_path) == ("body", "Torso", "you", None)


def test_removed_part_not_readded_on_analyse(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_analysis(monkeypatch, ai_analysis())
    with deps._factory()() as s:
        item = make_item(client, s)
        service.analyse(s, item.id)
        assert not part_row(s, item.id, "body").removed
        label.remove_part(s, item.id, "body")
        s.commit()
        item.parse_status = "completed"
        s.commit()
        service.analyse(s, item.id)
        body = part_row(s, item.id, "body")
        assert body.removed and body.source == "you"
        assert s.query(ItemPart).filter_by(item_id=item.id).count() == 1
        shape = attr(s, item.id, "shape")  # its physical dimension went with it
        assert shape.removed


def test_dimension_lifecycle_and_value_edit(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        label.add_part(s, item.id, "Body", None)
        row = label.add_dimension(s, item.id, "Surface finish", "physical", "body", None)
        assert (row.key, row.source, row.dim_type, row.part, row.status) == (
            "surface_finish", "user", "physical", "body", "missing",
        )  # fmt: skip
        assert row.spec_json["kind"] == "text"
        # the value is edited through the spec stored on the item, with no lens in play
        edited = edit_attribute(s, item.id, "surface_finish", "matte")
        assert (edited.value_json, edited.source) == ("matte", "user")
        up = label.update_dimension(s, item.id, "surface_finish", label="Finish", type="abstract",
                                    prompt="How does it feel?")  # fmt: skip
        assert (up.label, up.part, up.dim_type, up.prompt, up.key) == (
            "Finish", None, "abstract", "How does it feel?", "surface_finish",
        )  # fmt: skip
        label.remove_dimension(s, item.id, "surface_finish")
        s.commit()
        assert attr(s, item.id, "surface_finish").removed
        revived = label.add_dimension(s, item.id, "Surface finish", "abstract", None, "Finish?")
        assert not revived.removed and revived.value_json is None
        actions = [e.action for e in attrs_repo.events(s, item.id, "surface_finish")]
    assert actions == ["edited", "edited", "edited", "disabled", "edited"]


def test_add_dimension_abstract_needs_prompt(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        with pytest.raises(AppError) as e:
            label.add_dimension(s, item.id, "Mood", "abstract", None, None)
        assert e.value.status == 400
        with pytest.raises(AppError):  # physical without a part
            label.add_dimension(s, item.id, "Mood", "physical", None, None)
        with pytest.raises(AppError) as e2:  # physical on a part that does not exist
            label.add_dimension(s, item.id, "Mood", "physical", "nope", None)
    assert e2.value.code == "PART_NOT_FOUND"


def test_user_dimension_survives_analyse(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_analysis(monkeypatch, ai_analysis())
    with deps._factory()() as s:
        item = make_item(client, s)
        label.add_dimension(s, item.id, "Shape", "abstract", None, "What shape?")
        s.commit()
        service.analyse(s, item.id)
        row = attr(s, item.id, "shape")
    assert (row.source, row.dim_type, row.value_json) == ("user", "abstract", None)


def test_set_content_type_requeues_analysis(client: TestClient, env: list[str]) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        out = label.set_content_type(s, item.id, "ui")
        s.commit()
        assert out.content_type == "ui" and out.parse_status == "pending"
        with pytest.raises(AppError):
            label.set_content_type(s, item.id, "audio")
    assert env == [item.id]


def test_unknown_part_and_dimension_404(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        for call in (
            lambda: label.rename_part(s, item.id, "nope", "X"),
            lambda: label.remove_part(s, item.id, "nope"),
            lambda: label.remove_dimension(s, item.id, "nope"),
            lambda: label.update_dimension(s, item.id, "nope", label="X"),
        ):
            with pytest.raises(AppError) as e:
                call()
            assert e.value.status == 404


def test_content_type_survives_analyse(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)  # the mock reads this 4:3 image as "image"
        label.set_content_type(s, item.id, "ui")
        s.commit()
        assert item.content_type_locked
        item.parse_status = "completed"
        s.commit()
        service.analyse(s, item.id)
        s.expire_all()
        assert s.get(BoardItem, item.id).content_type == "ui"  # type: ignore[union-attr]
        kinds = {p.region_kind for p in s.query(ItemPart).filter_by(item_id=item.id)}
    assert kinds == {"box"}


def test_add_part_region_kind_must_fit_item(client: TestClient) -> None:
    with deps._factory()() as s:
        item = make_item(client, s)
        with pytest.raises(AppError) as e:
            label.add_part(s, item.id, "Intro", Region(kind="text_range", range=[0, 5]))
        assert (e.value.status, e.value.code) == (422, "REGION_KIND_MISMATCH")
        note = items_repo.create(
            s, board_id=item.board_id, kind="note", origin="note", note_text="hello world",
            rights_status="user_supplied", parse_status="completed",
        )  # fmt: skip
        with pytest.raises(AppError) as e2:
            label.add_part(s, note.id, "Box", Region(kind="box", box=[0, 0, 1, 1]))
    assert e2.value.code == "REGION_KIND_MISMATCH"
