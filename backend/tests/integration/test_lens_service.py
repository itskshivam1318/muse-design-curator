from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import events, jobs, lens_service
from app.board import votes
from app.db.models import BoardItem, CorpusItem
from app.db.repos import boards as boards_repo
from app.db.repos import items as items_repo
from app.db.repos import lenses as lenses_repo
from app.domain.lens import LensSpec
from app.errors import AppError
from app.providers.embedding import MockEmbedder
from app.providers.reasoning import MockReasoningProvider
from app.providers.segmentation import MockSegmentationProvider, SegResult
from app.storage import files
from tests.media import image_bytes

VALID_LENS: dict[str, Any] = {
    "label": "Thing",
    "notes": [],
    "parts": [
        {"id": "body", "sam_prompt": "body", "grounding": "sam"},
        {"id": "handle", "sam_prompt": "handle", "grounding": "sam"},
    ],
    "attributes": [
        {"key": "tone", "label": "Tone", "category": "c", "kind": "enum", "part": "body",
         "vocabulary": ["warm", "cool"]},
        {"key": "weight", "label": "Weight", "category": "c", "kind": "ordinal",
         "scale": ["light", "mid", "heavy"]},
    ],
}  # fmt: skip


@pytest.fixture(autouse=True)
def env(data_dir: Path) -> Iterator[None]:
    saved = dict(jobs._registry)
    yield
    jobs._registry.clear()
    jobs._registry.update(saved)


class SpyReasoning(MockReasoningProvider):
    def __init__(self, truth: dict[str, Any] | None = None) -> None:
        super().__init__(truth)
        self.calls: list[tuple[list[bytes], str, dict[str, Any]]] = []

    def propose_lens(self, images, context, schema):  # type: ignore[no-untyped-def]
        self.calls.append((images, context, schema))
        return super().propose_lens(images, context, schema)


@pytest.fixture
def reasoning(monkeypatch: pytest.MonkeyPatch) -> SpyReasoning:
    r = SpyReasoning(VALID_LENS)
    monkeypatch.setattr(lens_service, "get_reasoning", lambda _s: r)
    return r


@pytest.fixture(autouse=True)
def segmentation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lens_service, "get_segmentation", lambda _s: MockSegmentationProvider())


def make_board(session: Session, n: int, domain: str | None = None, status: str = "completed"):  # type: ignore[no-untyped-def]
    board = boards_repo.create(session, "B", domain=domain)
    imgs = [image_bytes(seed=i, size=(300, 300)) for i in range(n)]
    emb = MockEmbedder().embed_images(imgs)
    out: list[BoardItem] = []
    for i, data in enumerate(imgs):
        sha = files.sha256_hex(data)
        out.append(
            items_repo.create(
                session, board_id=board.id, kind="image", origin="upload", sha256=sha,
                storage_path=files.save_original(data, sha, "png"), parse_status=status,
                embedding_json=emb[i].tolist(), embedder_id="mock",
            )
        )  # fmt: skip
    session.flush()
    return board, out


def test_curated_lens_attached_when_domain_matches(session: Session) -> None:
    board, _ = make_board(session, 1, domain="ui")
    spec = lens_service.ensure_board_lens(session, board.id)
    assert spec is not None and spec.origin == "curated" and spec.domain == "ui"
    assert lens_service.curated_lens("ui") == spec
    row = lenses_repo.get(session, board.lens_id)
    assert row is not None and row.origin == "curated" and row.board_id == board.id
    assert row.status == "confirmed"


def test_no_proposal_under_5_items(session: Session, reasoning: SpyReasoning) -> None:
    board, _ = make_board(session, 4)
    assert lens_service.ensure_board_lens(session, board.id) is None
    assert reasoning.calls == []
    assert lenses_repo.latest(session, board.id, "custom") is None


def test_ensure_proposes_at_five_and_not_twice(session: Session, reasoning: SpyReasoning) -> None:
    board, _ = make_board(session, 5)
    assert lens_service.ensure_board_lens(session, board.id) is None
    assert len(reasoning.calls) == 1
    assert lens_service.ensure_board_lens(session, board.id) is None
    assert len(reasoning.calls) == 1
    assert lenses_repo.latest(session, board.id, "custom").status == "proposed"  # type: ignore[union-attr]


def test_proposal_sampled_from_board_items_max_20(
    session: Session, reasoning: SpyReasoning
) -> None:
    board, items = make_board(session, 30)
    lens_service.propose_lens(session, board.id)
    images = reasoning.calls[0][0]
    assert len(images) == 20 and len(set(images)) == 20
    board_bytes = {files.abs_path(i.storage_path or "").read_bytes() for i in items}
    assert set(images) <= board_bytes
    assert reasoning.calls[0][2] == LensSpec.model_json_schema()


def test_farthest_point_sampling_prefers_diverse(session: Session) -> None:
    _board, items = make_board(session, 6)
    for i, it in enumerate(items):  # five near-identical, one outlier
        it.embedding_json = [1.0, 0.0] if i < 5 else [0.0, 1.0]
    picked = lens_service.sample_diverse(items, 2)
    assert items[5] in picked and len(picked) == 2


def test_proposed_lens_validates_with_origin_proposed(
    session: Session, reasoning: SpyReasoning
) -> None:
    board, _ = make_board(session, 5)
    boards_repo.update(session, board.id, domain="mug")
    seen: list[dict[str, Any]] = []
    sub = events.subscribe(board.id)
    spec = lens_service.propose_lens(session, board.id)
    while (ev := sub.get(timeout=0.01)) is not None:
        seen.append(ev)
    sub.close()
    assert spec.origin == "proposed" and spec.id == "mug@1" and spec.domain == "mug"
    row = lenses_repo.latest(session, board.id, "mug")
    assert row is not None and row.status == "proposed" and row.origin == "proposed"
    assert LensSpec.model_validate(row.spec_json) == spec
    assert [e["type"] for e in seen] == ["lens.proposed"]


def test_custom_domain_when_board_has_none(session: Session, reasoning: SpyReasoning) -> None:
    board, _ = make_board(session, 5)
    assert lens_service.propose_lens(session, board.id).id == "custom@1"


def test_invalid_proposal_is_502_and_stores_nothing(session: Session) -> None:
    board, _ = make_board(session, 5)
    # default mock output (no truth) is not a valid LensSpec
    with pytest.raises(AppError) as e:
        lens_service.propose_lens(session, board.id)
    assert e.value.status == 502 and e.value.code == "LENS_PROPOSAL_INVALID"
    assert lenses_repo.latest(session, board.id, "custom") is None


class PartialSeg:
    id = "t"
    is_mock = True

    def __init__(self) -> None:
        self.mock = MockSegmentationProvider()

    def localize(self, image: bytes, sha256: str, noun: str) -> SegResult:
        return self.mock.localize(image, sha256, noun) if noun == "body" else SegResult()


def test_low_hit_part_falls_back_to_whole_image_with_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lens_service, "get_segmentation", lambda _s: PartialSeg())
    lens = LensSpec.model_validate({**VALID_LENS, "id": "x@1", "domain": "x", "origin": "proposed"})
    out = lens_service.prune_parts(lens, [image_bytes(seed=i) for i in range(12)])
    by = {p.id: p for p in out.parts}
    assert by["body"].grounding == "sam" and by["handle"].grounding == "whole_image"
    assert len(out.notes) == 1 and "handle" in out.notes[0]
    assert lens.parts[1].grounding == "sam"  # input untouched


def test_prune_uses_at_most_10_images(monkeypatch: pytest.MonkeyPatch) -> None:
    seg = PartialSeg()
    n = 0
    orig = seg.localize

    def counting(image, sha, noun):  # type: ignore[no-untyped-def]
        nonlocal n
        n += 1
        return orig(image, sha, noun)

    seg.localize = counting  # type: ignore[method-assign]
    monkeypatch.setattr(lens_service, "get_segmentation", lambda _s: seg)
    lens = LensSpec.model_validate({**VALID_LENS, "id": "x@1", "domain": "x", "origin": "proposed"})
    lens_service.prune_parts(lens, [image_bytes(seed=i) for i in range(15)])
    assert n == 20  # 2 parts x 10 images


def test_confirm_with_edits_creates_version_2_and_v1_readable(
    session: Session, reasoning: SpyReasoning
) -> None:
    board, _ = make_board(session, 5)
    v1 = lens_service.propose_lens(session, board.id)
    edited = v1.model_copy(update={"label": "Edited"})
    lens_service.confirm_lens(session, board.id, edited)
    rows = lenses_repo.versions(session, board.id, "custom")
    assert [r.version for r in rows] == [1, 2]
    assert rows[1].origin == "edited" and rows[1].status == "confirmed"
    assert LensSpec.model_validate(rows[1].spec_json).id == "custom@2"
    assert LensSpec.model_validate(rows[0].spec_json).label == "Thing"
    assert board.lens_id == rows[1].id


def test_confirm_as_is(session: Session, reasoning: SpyReasoning) -> None:
    board, _ = make_board(session, 5)
    lens_service.propose_lens(session, board.id)
    lens_service.confirm_lens(session, board.id, None)
    row = lenses_repo.latest(session, board.id, "custom")
    assert row is not None and row.status == "confirmed" and row.version == 1
    assert board.lens_id == row.id


def test_pending_lens_items_requeued_after_confirmation(
    session: Session, reasoning: SpyReasoning
) -> None:
    board, items = make_board(session, 5, status="pending_lens")
    items[0].parse_status = "completed"
    queued: list[str] = []
    jobs.register("parse_item", lambda item_id: queued.append(item_id))
    lens_service.propose_lens(session, board.id)
    lens_service.confirm_lens(session, board.id, None)
    assert sorted(queued) == sorted(i.id for i in items[1:])
    assert all(i.parse_status == "pending" for i in items[1:])
    assert items[0].parse_status == "completed"


def test_mixed_domain_board_is_409_lens_ambiguous(
    session: Session, reasoning: SpyReasoning, monkeypatch: pytest.MonkeyPatch
) -> None:
    board, _ = make_board(session, 5)
    monkeypatch.setattr(lens_service, "domain_votes", lambda _s, _i: {"aa": 0.6, "bb": 0.4})
    with pytest.raises(AppError) as e:
        lens_service.ensure_board_lens(session, board.id)
    assert e.value.status == 409 and e.value.code == "LENS_AMBIGUOUS"
    assert e.value.details == {"candidates": ["aa", "bb"]}
    assert reasoning.calls == []


def test_clear_majority_is_not_ambiguous(
    session: Session, reasoning: SpyReasoning, monkeypatch: pytest.MonkeyPatch
) -> None:
    board, _ = make_board(session, 5)
    monkeypatch.setattr(lens_service, "domain_votes", lambda _s, _i: {"aa": 0.8, "bb": 0.2})
    assert lens_service.ensure_board_lens(session, board.id) is None
    assert len(reasoning.calls) == 1


# ---- domain_votes ----


def _corpus(session: Session, domain: str, row: int) -> None:
    session.add(
        CorpusItem(
            domain=domain, source="s", source_id=f"{domain}{row}", landing_url="u", image_url="u",
            license_code="x", attribution_text="a", embedding_row=row, indexing_status="indexed",
        )
    )  # fmt: skip


def test_domain_votes_empty_without_embeddings_file(session: Session) -> None:
    _board, items = make_board(session, 3)
    assert votes.domain_votes(session, items) == {}


def test_domain_votes_shares_and_ambiguity(session: Session, data_dir: Path) -> None:
    _board, items = make_board(session, 5)
    data_dir.mkdir(parents=True, exist_ok=True)
    np.save(data_dir / "embeddings.npy", np.array([[1.0, 0], [0.9, 0.1], [0, 1.0], [0.1, 0.9]]))
    _corpus(session, "ui", 0)
    _corpus(session, "ui", 1)
    _corpus(session, "watch", 2)
    _corpus(session, "watch", 3)
    session.flush()
    for i, it in enumerate(items):
        it.embedding_json = [1.0, 0.0] if i < 3 else [0.0, 1.0]
    v = votes.domain_votes(session, items)
    assert v == {"ui": 0.6, "watch": 0.4}
    assert votes.ambiguous_candidates(v) == ["ui", "watch"]
    assert votes.ambiguous_candidates({"ui": 0.8, "watch": 0.2}) is None
    assert votes.ambiguous_candidates({}) is None


# ---- API ----


def _db(client: TestClient):  # type: ignore[no-untyped-def]
    from app.api.deps import get_session
    from app.main import app

    return app.dependency_overrides[get_session]()


def test_api_flow(client: TestClient, reasoning: SpyReasoning) -> None:
    bid = client.post("/api/boards", json={"title": "T"}).json()["id"]
    r = client.post(f"/api/boards/{bid}/lens:propose")
    assert r.status_code == 409 and r.json()["error"]["code"] == "LENS_NOT_ENOUGH_ITEMS"

    gen = _db(client)
    s = next(gen)
    for i in range(5):
        data = image_bytes(seed=i, size=(300, 300))
        sha = files.sha256_hex(data)
        items_repo.create(
            s, board_id=bid, kind="image", origin="upload", sha256=sha,
            storage_path=files.save_original(data, sha, "png"), parse_status="completed",
            embedding_json=MockEmbedder().embed_images([data])[0].tolist(),
        )  # fmt: skip
    s.commit()
    gen.close()

    r = client.post(f"/api/boards/{bid}/lens:propose")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "proposed" and body["spec"]["origin"] == "proposed"
    lid = body["id"]
    assert client.get(f"/api/lenses/{lid}").json()["spec"]["id"] == "custom@1"
    assert client.get("/api/lenses/nope").status_code == 404

    bad = client.put(f"/api/boards/{bid}/lens", json={"id": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "VALIDATION_ERROR"

    ok = client.put(f"/api/boards/{bid}/lens")
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
    assert client.get(f"/api/boards/{bid}").json()["lens_id"] == lid

    spec = {**body["spec"], "label": "Mine"}
    ed = client.put(f"/api/boards/{bid}/lens", json=spec)
    assert ed.status_code == 200
    assert ed.json()["origin"] == "edited" and ed.json()["version"] == 2
    assert client.get(f"/api/lenses/{lid}").json()["version"] == 1
    assert client.get(f"/api/boards/{bid}").json()["lens_id"] == ed.json()["id"]
