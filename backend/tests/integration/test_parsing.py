import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import events, jobs
from app.api import deps
from app.board import profile_hook
from app.db.models import BoardItem, ModelCache
from app.db.repos import attributes as attrs_repo
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.repos import lenses as lenses_repo
from app.domain.lens import LensSpec
from app.errors import AppError
from app.extraction import service
from app.providers.reasoning import MockReasoningProvider
from app.providers.reliability import ModelError
from app.providers.segmentation import MockSegmentationProvider
from app.storage import files
from tests.media import image_bytes, video_bytes

LENS: dict[str, Any] = {
    "id": "thing@1", "domain": "thing", "label": "Thing", "origin": "edited",
    "parts": [{"id": "body", "sam_prompt": "body", "grounding": "sam"}],
    "attributes": [
        {"key": "body_color", "label": "Body colour", "category": "c", "kind": "color",
         "part": "body"},
        {"key": "bg_color", "label": "Background", "category": "c", "kind": "color"},
        {"key": "tone", "label": "Tone", "category": "c", "kind": "enum", "part": "body",
         "vocabulary": ["warm", "cool"]},
        {"key": "weight", "label": "Weight", "category": "c", "kind": "ordinal",
         "scale": ["light", "mid", "heavy"]},
        {"key": "size_mm", "label": "Size", "category": "c", "kind": "number", "unit": "mm",
         "min": 0, "max": 100, "tolerance": 5},
        {"key": "coverage", "label": "Coverage", "category": "c", "kind": "number",
         "unit": "ratio", "min": 0, "max": 1, "tolerance": 0.1, "measure": "mask_ratio",
         "part": "body"},
        {"key": "has_logo", "label": "Logo", "category": "c", "kind": "boolean"},
        {"key": "summary", "label": "Summary", "category": "c", "kind": "text"},
    ],
}  # fmt: skip
TRUTH: dict[str, Any] = {
    "kind": "region", "tone": "warm", "weight": "heavy", "size_mm": 42, "has_logo": True,
    "summary": "a thing",
}  # fmt: skip


class Fake(MockReasoningProvider):
    def __init__(self, truth: dict[str, Any] | None = None) -> None:
        super().__init__(TRUTH if truth is None else truth)
        self.calls: list[tuple[list[bytes], dict[str, Any], str]] = []
        self.hook: Any = None
        self.raises: BaseException | None = None
        self.response: Any = None

    def extract(self, images, schema, prompt):  # type: ignore[no-untyped-def]
        self.calls.append((images, schema, prompt))
        if self.hook:
            self.hook()
        if self.raises:
            raise self.raises
        if self.response is not None:
            return self.response
        return super().extract(images, schema, prompt)


class CountingSeg(MockSegmentationProvider):
    n = 0

    def localize(self, image, sha256, noun):  # type: ignore[no-untyped-def]
        type(self).n += 1
        return super().localize(image, sha256, noun)


@pytest.fixture(autouse=True)
def env(data_dir: Path) -> Iterator[None]:
    saved = dict(jobs._registry)
    CountingSeg.n = 0
    yield
    jobs._registry.clear()
    jobs._registry.update(saved)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Fake:
    p = Fake()
    monkeypatch.setattr(service, "get_reasoning", lambda _s: p)
    monkeypatch.setattr(service, "get_segmentation", lambda _s: CountingSeg())
    return p


def two_tone() -> bytes:
    arr = np.zeros((300, 300, 3), np.uint8)
    arr[:] = (0, 0, 255)
    arr[60:240, 60:240] = (255, 0, 0)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def lens_board(session: Session, spec: dict[str, Any] | None = None, context: str = "") -> str:
    board = boards_repo.create(session, "B", context=context)
    lens = LensSpec.model_validate(spec or LENS)
    row = lenses_repo.save(
        session, board.id, lens.domain, "edited", lens.model_dump(mode="json"), status="confirmed"
    )
    board.lens_id = row.id
    session.flush()
    return board.id


def add_item(session: Session, board_id: str, data: bytes | None = None) -> BoardItem:
    data = data or two_tone()
    sha = files.sha256_hex(data)
    item = items_repo.create(
        session, board_id=board_id, kind="image", origin="upload", sha256=sha,
        storage_path=files.save_original(data, sha, "png"),
    )  # fmt: skip
    session.commit()
    return item


def attr(session: Session, item_id: str, key: str) -> Any:
    session.expire_all()
    return next(a for a in attrs_repo.for_item(session, item_id) if a.key == key)


def test_ordinal_extracted_as_scale_value(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    a = attr(session, item.id, "weight")
    assert (a.value_json, a.status, a.source, a.confidence) == ("heavy", "extracted", "mock", 0.9)
    assert items_repo.get(session, item.id).parse_status == "completed"  # type: ignore[union-attr]
    assert attr(session, item.id, "tone").value_json == "warm"


def test_number_outside_range_is_missing(session: Session, provider: Fake) -> None:
    provider.truth = {**TRUTH, "size_mm": 500}
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    a = attr(session, item.id, "size_mm")
    assert a.value_json is None and a.status == "missing"


def test_boolean_without_evidence_is_missing(session: Session, provider: Fake) -> None:
    provider.truth = {**TRUTH, "kind": "none"}
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    a = attr(session, item.id, "has_logo")
    assert a.value_json is None and a.status == "missing"


def test_colour_comes_from_measurement_not_model(session: Session, provider: Fake) -> None:
    provider.truth = {**TRUTH, "body_color": "purple", "bg_color": "purple"}
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    schema = provider.calls[0][1]
    assert "body_color" not in schema["properties"] and "coverage" not in schema["properties"]
    body = attr(session, item.id, "body_color")
    assert (body.value_json, body.source, body.status) == ("red", "measured", "extracted")
    assert body.measured_json["hex"].startswith("#") and len(body.measured_json["lab"]) == 3
    assert attr(session, item.id, "bg_color").value_json == "blue"
    cov = attr(session, item.id, "coverage")
    assert cov.source == "measured" and cov.value_json == pytest.approx(0.36, abs=0.02)


def test_embedding_and_palette_stored(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    session.expire_all()
    it = items_repo.get(session, item.id)
    assert it and len(it.embedding_json) == 64 and it.embedder_id == "mock" and it.palette_json


def test_masks_cached_across_reparse(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    service.parse_item(session, item.id)
    assert CountingSeg.n == 1


def test_edited_value_survives_reparse(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    service.edit_attribute(session, item.id, "weight", value="light")
    session.commit()
    service.parse_item(session, item.id)
    a = attr(session, item.id, "weight")
    assert (a.value_json, a.status, a.source, a.model_value_json) == (
        "light",
        "edited",
        "user",
        "heavy",
    )
    actions = [e.action for e in attrs_repo.events(session, item.id, "weight")]
    assert actions == ["extracted", "edited", "model_suppressed"]


def test_disabled_stays_disabled(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    service.edit_attribute(session, item.id, "tone", action="disable")
    session.commit()
    service.parse_item(session, item.id)
    a = attr(session, item.id, "tone")
    assert a.enabled is False and a.value_json == "warm"


def test_timeout_fails_and_keeps_prior_attributes(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    session.execute(delete(ModelCache))
    session.commit()
    provider.raises = ModelError("MODEL_TIMEOUT")
    service.parse_item(session, item.id)
    session.expire_all()
    it = items_repo.get(session, item.id)
    assert it and (it.parse_status, it.parse_error_code, it.parse_attempts) == (
        "failed",
        "MODEL_TIMEOUT",
        2,
    )
    assert attr(session, item.id, "weight").value_json == "heavy"


def test_unexpected_exception_is_parse_error(session: Session, provider: Fake) -> None:
    provider.raises = RuntimeError("boom")
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    session.expire_all()
    it = items_repo.get(session, item.id)
    assert it and (it.parse_status, it.parse_error_code) == ("failed", "PARSE_ERROR")


@pytest.mark.parametrize("bad", [["not", "an", "object"], {"unrelated": 1}])
def test_invalid_response_fails(session: Session, provider: Fake, bad: Any) -> None:
    provider.response = bad
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    session.expire_all()
    it = items_repo.get(session, item.id)
    assert it and (it.parse_status, it.parse_error_code) == ("failed", "MODEL_INVALID_RESPONSE")


def test_retry_does_not_duplicate_rows(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    service.parse_item(session, item.id)
    n = len(attrs_repo.for_item(session, item.id))
    service.parse_item(session, item.id)
    assert len(attrs_repo.for_item(session, item.id)) == n == len(LENS["attributes"])
    assert len(provider.calls) == 1  # second parse hit the model cache


def test_concurrent_parse_is_409(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))
    seen: list[AppError] = []

    def second() -> None:
        other = Session(session.get_bind())
        try:
            service.parse_item(other, item.id)
        except AppError as e:
            seen.append(e)
        finally:
            other.close()

    provider.hook = second
    service.parse_item(session, item.id)
    assert [(e.status, e.code) for e in seen] == [(409, "PARSE_IN_PROGRESS")]
    with pytest.raises(AppError):
        session.execute(
            BoardItem.__table__.update()
            .where(BoardItem.id == item.id)
            .values(parse_status="processing")
        )
        service.parse_item(session, item.id)


def test_edit_during_processing_survives_completion(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session))

    def edit() -> None:
        other = Session(session.get_bind())
        service.edit_attribute(other, item.id, "weight", value="light")
        other.commit()
        other.close()

    provider.hook = edit
    service.parse_item(session, item.id)
    a = attr(session, item.id, "weight")
    assert (a.value_json, a.status, a.model_value_json) == ("light", "edited", "heavy")
    assert items_repo.get(session, item.id).parse_status == "completed"  # type: ignore[union-attr]


def test_no_lens_stops_at_pending_lens_after_embedding(session: Session, provider: Fake) -> None:
    board = boards_repo.create(session, "B")
    item = add_item(session, board.id)
    seen: list[dict[str, Any]] = []
    sub = events.subscribe(board.id)
    service.parse_item(session, item.id)
    while (ev := sub.get(timeout=0.05)) is not None:
        seen.append(ev)
    sub.close()
    session.expire_all()
    it = items_repo.get(session, item.id)
    assert it and it.parse_status == "pending_lens" and it.embedding_json and it.palette_json
    assert provider.calls == []
    assert [e["type"] for e in seen] == ["item.parsed"] and seen[0]["data"]["pending_lens"] is True


def test_events_and_recompute_hook(
    session: Session, provider: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(profile_hook, "request_recompute", called.append)
    board_id = lens_board(session)
    item = add_item(session, board_id)
    sub = events.subscribe(board_id)
    service.parse_item(session, item.id)
    session.execute(delete(ModelCache))
    session.commit()
    provider.raises = ModelError("MODEL_TIMEOUT")
    service.parse_item(session, item.id)
    types = []
    while (ev := sub.get(timeout=0.05)) is not None:
        types.append(ev["type"])
    sub.close()
    assert types == ["item.parsed", "item.failed"] and called == [board_id, board_id]


def test_context_and_image_sent_to_model(session: Session, provider: Fake) -> None:
    item = add_item(session, lens_board(session, context="vintage things"))
    service.parse_item(session, item.id)
    images, _schema, prompt = provider.calls[0]
    assert images == [two_tone()] and "vintage things" in prompt


def test_video_parsed_from_chosen_frame_and_choosing_reparses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = Fake()
    monkeypatch.setattr(service, "get_reasoning", lambda _s: p)
    board = client.post("/api/boards", json={"title": "V", "domain": "ui"}).json()
    r = client.post(
        f"/api/boards/{board['id']}/items",
        files=[("files[]", ("v.mp4", video_bytes([0, 1, 2, 3]), "video/mp4"))],
    )
    item = r.json()["results"][0]["item"]
    data = client.get(f"/api/items/{item['id']}/attributes").json()
    assert data["parse_status"] == "completed" and len(p.calls) == 1
    fs = _frames(client, item["id"])
    chosen = next(f for f in fs if f.chosen)
    assert p.calls[0][0] == [files.abs_path(chosen.storage_path).read_bytes()]
    other = next(f for f in fs if not f.chosen)
    r = client.patch(f"/api/items/{item['id']}", json={"chosen_frame_id": other.id})
    assert r.status_code == 200
    assert len(p.calls) == 2
    assert p.calls[1][0] == [files.abs_path(other.storage_path).read_bytes()]


def _frames(client: TestClient, item_id: str) -> list[Any]:
    with deps._factory()() as s:
        return items_repo.frames(s, item_id)


def test_same_service_parses_two_boards_with_own_lenses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = Fake({})
    monkeypatch.setattr(service, "get_reasoning", lambda _s: p)
    out = {}
    for domain in ("watch", "ui"):
        b = client.post("/api/boards", json={"title": domain, "domain": domain}).json()
        up = client.post(
            f"/api/boards/{b['id']}/items",
            files=[("files[]", ("a.png", image_bytes(seed=3), "image/png"))],
        ).json()["results"][0]["item"]
        out[domain] = client.get(f"/api/items/{up['id']}/attributes").json()
    keys = {d: {a["key"] for a in v["attributes"]} for d, v in out.items()}
    lens_keys = {d: {a["key"] for a in v["lens"]["attributes"]} for d, v in out.items()}
    assert keys["watch"] == lens_keys["watch"] != lens_keys["ui"] == keys["ui"]
    assert {v["parse_status"] for v in out.values()} == {"completed"}


# ---- API ----


@pytest.fixture
def parsed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Fake]:
    p = Fake({"kind": "region", "background_tone": "dark", "has_illustration": True})
    monkeypatch.setattr(service, "get_reasoning", lambda _s: p)
    b = client.post("/api/boards", json={"title": "u", "domain": "ui"}).json()
    up = client.post(
        f"/api/boards/{b['id']}/items",
        files=[("files[]", ("a.png", image_bytes(seed=5), "image/png"))],
    ).json()["results"][0]["item"]
    return up["id"], p


def test_get_attributes_shape(client: TestClient, parsed: tuple[str, Fake]) -> None:
    item_id, _ = parsed
    d = client.get(f"/api/items/{item_id}/attributes").json()
    assert d["provider"] == {"id": "mock", "model": "mock-reasoning", "is_mock": True}
    assert d["lens"]["domain"] == "ui" and d["parse_status"] == "completed"
    tone = next(a for a in d["attributes"] if a["key"] == "background_tone")
    assert tone["value"] == "dark" and tone["status"] == "extracted"


def test_patch_edit_confirm_disable_and_history(
    client: TestClient, parsed: tuple[str, Fake]
) -> None:
    item_id, _ = parsed
    url = f"/api/items/{item_id}/attributes"
    r = client.patch(f"{url}/density", json={"value": "spacious"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_ATTRIBUTE_VALUE"
    r = client.patch(f"{url}/nope", json={"value": "x"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNKNOWN_ATTRIBUTE"
    r = client.patch(f"{url}/background_tone", json={"value": "light"})
    body = r.json()
    assert (body["value"], body["status"], body["source"], body["confidence"]) == (
        "light",
        "edited",
        "user",
        1.0,
    )
    assert body["evidence"]["kind"] == "none"
    r = client.patch(f"{url}/background_tone", json={"action": "confirm"})
    assert r.json()["status"] == "confirmed"
    r = client.patch(f"{url}/background_tone", json={"action": "disable"})
    assert r.json()["enabled"] is False
    r = client.patch(f"{url}/background_tone", json={"action": "enable"})
    assert r.json()["enabled"] is True
    assert client.patch(f"{url}/background_tone", json={}).status_code == 400
    hist = client.get(f"{url}/background_tone/history").json()["events"]
    assert [e["action"] for e in hist] == [
        "extracted",
        "edited",
        "confirmed",
        "disabled",
        "enabled",
    ]
    assert hist[1]["before"]["value"] == "dark" and hist[1]["after"]["value"] == "light"


def test_post_parse_retries_failed_item(client: TestClient, parsed: tuple[str, Fake]) -> None:
    item_id, p = parsed
    with deps._factory()() as s:
        s.execute(delete(ModelCache))
        s.commit()
    p.raises = ModelError("MODEL_TIMEOUT")
    r = client.post(f"/api/items/{item_id}/parse")
    assert r.status_code == 202
    assert client.get(f"/api/items/{item_id}/attributes").json()["parse_status"] == "failed"
    p.raises = None
    client.post(f"/api/items/{item_id}/parse")
    assert client.get(f"/api/items/{item_id}/attributes").json()["parse_status"] == "completed"
    assert client.post("/api/items/item_missing/parse").status_code == 404


def test_frame_changed_during_parse_requeues(session: Session, provider: Fake) -> None:
    from app.ingest.common import ItemMeta
    from app.ingest.video import choose_frame, ingest_video

    board_id = lens_board(session)
    item = ingest_video(session, board_id, video_bytes([0, 1, 2, 3]), ItemMeta()).item
    session.commit()
    queued: list[str] = []
    jobs.register("parse_item", lambda item_id: queued.append(item_id))
    other = next(f for f in items_repo.frames(session, item.id) if not f.chosen)

    def switch() -> None:
        s2 = Session(session.get_bind())
        choose_frame(s2, item.id, other.id)
        s2.commit()
        s2.close()

    provider.hook = switch
    service.parse_item(session, item.id)
    session.expire_all()
    assert items_repo.get(session, item.id).parse_status == "pending"  # type: ignore[union-attr]
    assert queued == [item.id]


def test_whole_image_part_is_measured_on_the_whole_image(session: Session, provider: Fake) -> None:
    spec = {
        **LENS,
        "parts": [{"id": "body", "sam_prompt": "body", "grounding": "whole_image"}],
    }
    item = add_item(session, lens_board(session, spec))
    service.parse_item(session, item.id)
    body = attr(session, item.id, "body_color")
    assert (body.value_json, body.status, body.source) == ("blue", "extracted", "measured")
    cov = attr(session, item.id, "coverage")
    assert cov.value_json == 1.0 and CountingSeg.n == 0


def test_no_write_lock_held_during_model_call(tmp_path: Path, provider: Fake) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.db.session import make_engine, run_migrations

    url = f"sqlite:///{tmp_path / 'lock.sqlite'}"
    engine = make_engine(url)
    run_migrations(engine)
    other = make_engine(url, connect_args={"timeout": 0.5})
    with Session(engine) as s:
        item = add_item(s, lens_board(s))
        outcome: list[str] = []

        def concurrent_write() -> None:
            try:
                with other.begin() as conn:
                    conn.execute(text("UPDATE boards SET title = 'edited'"))
                outcome.append("ok")
            except OperationalError as exc:  # database is locked
                outcome.append(repr(exc))

        provider.hook = concurrent_write
        service.parse_item(s, item.id)
    assert outcome == ["ok"]
    engine.dispose()
    other.dispose()
