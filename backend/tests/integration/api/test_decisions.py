from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import BoardItem, CorpusItem, Decision, RunCandidate, VariationRun
from app.db.repos import attributes as attrs_repo
from app.db.repos import profiles as profiles_repo
from tests.integration.api.test_runs import post


def setup(client: TestClient, world: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rid = post(client, world).json()["run_id"]
    top = client.get(f"/api/runs/{rid}").json()["results"][0]
    free_sha(world, top)
    return rid, top


def free_sha(world: dict[str, Any], top: dict[str, Any]) -> None:
    """The seeded board already holds corpus images; clear the candidate's twin (not the source)."""
    s = world["session"]
    sha = s.get(CorpusItem, top["corpus_item_id"]).sha256
    src = s.get(VariationRun, top["id"] and s.get(RunCandidate, top["id"]).run_id).source_item_id
    for i in s.scalars(select(BoardItem).where(BoardItem.sha256 == sha, BoardItem.id != src)):
        i.removed_at = "2026-01-01T00:00:00Z"
    s.commit()


def decide(client: TestClient, rid: str, cid: str, **body: Any):  # type: ignore[no-untyped-def]
    headers = {"Idempotency-Key": body.pop("key")} if "key" in body else {}
    return client.post(f"/api/runs/{rid}/candidates/{cid}/decisions", json=body, headers=headers)


def n_items(world: dict[str, Any]) -> int:
    s = world["session"]
    s.expire_all()
    return s.scalar(select(func.count()).select_from(BoardItem).where(
        BoardItem.board_id == world["watch"]))  # type: ignore[return-value]


def test_keep_persists_with_board_run_candidate_and_timestamp(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    r = decide(client, rid, top["id"], decision="keep")
    assert r.status_code == 201
    body = r.json()
    s = world["session"]
    s.expire_all()
    d = s.get(Decision, body["decision"]["id"])
    assert d.board_id == world["watch"] and d.run_id == rid and d.run_candidate_id == top["id"]
    assert d.corpus_item_id == top["corpus_item_id"] and d.created_at and d.decision == "keep"
    assert d.item_id == body["item"]["id"]


def test_keep_creates_exactly_one_linked_item_even_when_posted_twice(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    before = n_items(world)
    a = decide(client, rid, top["id"], decision="keep").json()
    b = decide(client, rid, top["id"], decision="keep").json()
    assert n_items(world) == before + 1
    assert a["item"]["id"] == b["item"]["id"] and len(b["history"]) == 2
    s = world["session"]
    s.expire_all()
    assert s.scalar(select(func.count()).select_from(Decision)) == 2
    # idempotency key replays without a new row
    c = decide(client, rid, top["id"], decision="keep", key="k1")
    d = decide(client, rid, top["id"], decision="keep", key="k1")
    assert c.json() == d.json()
    s.expire_all()
    assert s.scalar(select(func.count()).select_from(Decision)) == 3
    e = decide(client, rid, top["id"], decision="reject", key="k1")
    assert e.status_code == 409 and e.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_kept_item_carries_licence_credit_and_parent_link(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    item = decide(client, rid, top["id"], decision="keep").json()["item"]
    s = world["session"]
    s.expire_all()
    row = s.get(BoardItem, item["id"])
    run = client.get(f"/api/runs/{rid}").json()["run"]
    parent = s.get(BoardItem, run["source_item_id"])
    assert row.origin == "candidate" and row.rights_status == "licensed"
    assert row.role == "reference" and row.parse_status == "completed"
    assert row.corpus_item_id == top["corpus_item_id"] and row.parent_item_id == parent.id
    assert row.x >= parent.x + parent.w + 24  # beside the parent, clear of other items
    assert max(row.w, row.h) <= 320 and row.storage_path and row.thumb_path
    assert row.page_url == top["provenance"]["landing_url"]
    attrs = {a.key: a for a in attrs_repo.for_item(s, row.id)}
    assert attrs and all(a.source == "corpus_index" for a in attrs.values())
    assert "dial_color" in attrs and attrs["dial_color"].value_json is not None
    got = client.get(f"/api/runs/{rid}").json()["results"][0]
    assert got["decision"]["item_id"] == row.id


def test_second_kept_item_does_not_overlap_the_first(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, _top = setup(client, world)
    results = client.get(f"/api/runs/{rid}").json()["results"]
    ids = [decide(client, rid, r["id"], decision="keep").json()["item"]["id"] for r in results[:3]]
    s = world["session"]
    s.expire_all()
    rows = [s.get(BoardItem, i) for i in ids]
    assert len(rows) == 3
    for a in rows:
        for b in rows:
            if a is not b:
                assert (
                    a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y
                )


def test_keep_then_reject_appends_history_latest_is_reject(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    decide(client, rid, top["id"], decision="keep")
    r = decide(client, rid, top["id"], decision="reject", reason_code="not_my_style", note="meh")
    assert [h["decision"] for h in r.json()["history"]] == ["reject", "keep"]
    got = client.get(f"/api/runs/{rid}").json()["results"][0]
    assert got["decision"]["decision"] == "reject" and len(got["decisions"]) == 2
    assert got["decision"]["reason_code"] == "not_my_style"


def test_reason_on_keep_is_400(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    assert decide(client, rid, top["id"], decision="keep", reason_code="other").status_code == 400
    assert decide(client, rid, top["id"], decision="keep", note="x").status_code == 400
    assert decide(client, rid, top["id"], decision="reject", reason_code="zzz").status_code == 400
    assert decide(client, rid, top["id"], decision="reject", note="x" * 501).status_code == 400
    assert decide(client, rid, top["id"], decision="reject", note="x" * 500).status_code == 201


def test_decision_on_excluded_candidate_is_409(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    s = world["session"]
    s.get(RunCandidate, top["id"]).state = "excluded"
    s.commit()
    r = decide(client, rid, top["id"], decision="keep")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CANDIDATE_NOT_DECIDABLE"


def test_candidate_from_another_run_is_404(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    other = post(client, world).json()["run_id"]
    assert decide(client, other, top["id"], decision="keep").status_code == 404
    assert decide(client, rid, "nope", decision="keep").status_code == 404


def test_reject_without_mark_not_this_changes_nothing_else(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    s = world["session"]
    before, pv = n_items(world), profiles_repo.latest(s, world["watch"])
    r = decide(client, rid, top["id"], decision="reject", reason_code="image_quality")
    assert r.status_code == 201 and r.json()["item"] is None
    assert n_items(world) == before
    s.expire_all()
    after = profiles_repo.latest(s, world["watch"])
    assert (after.version if after else 0) == (pv.version if pv else 0)


def test_reject_with_mark_not_this_creates_counter_example_and_keep_flips(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    before = n_items(world)
    r = decide(client, rid, top["id"], decision="reject", reason_code="other", mark_not_this=True)
    item = r.json()["item"]
    assert item["role"] == "counter_example" and n_items(world) == before + 1
    k = decide(client, rid, top["id"], decision="keep").json()
    assert k["item"]["id"] == item["id"] and k["item"]["role"] == "reference"
    assert n_items(world) == before + 1


def test_csv_export(client, world) -> None:  # type: ignore[no-untyped-def]
    rid, top = setup(client, world)
    decide(client, rid, top["id"], decision="keep")
    decide(client, rid, top["id"], decision="reject", reason_code="other", note="a, b")
    r = client.get(f"/api/boards/{world['watch']}/decisions.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == (
        "created_at,run_id,candidate_id,corpus_item_id,decision,reason_code,note,item_id"
    )
    assert len(lines) == 3 and ",reject,other," in lines[1] and ",keep," in lines[2]
    assert client.get("/api/boards/nope/decisions.csv").status_code == 404


def test_keep_links_existing_item_with_same_image(client, world) -> None:  # type: ignore[no-untyped-def]
    rid = post(client, world).json()["run_id"]
    top = client.get(f"/api/runs/{rid}").json()["results"][0]
    s = world["session"]
    sha = s.get(CorpusItem, top["corpus_item_id"]).sha256
    twin = s.scalars(select(BoardItem).where(
        BoardItem.sha256 == sha, BoardItem.removed_at.is_(None))).first()
    if twin is None:
        return  # candidate image not on this board
    before = n_items(world)
    got = decide(client, rid, top["id"], decision="keep").json()
    assert got["item"]["id"] == twin.id and n_items(world) == before


def test_csv_neutralises_formulas_and_round_trips(client, world) -> None:  # type: ignore[no-untyped-def]
    import csv
    import io

    rid, top = setup(client, world)
    notes = ['=HYPERLINK("x")', "+1", "-2", "@cmd", "\tTab", "line1\nline2", 'say "hi", ok']
    for n in notes:
        assert decide(client, rid, top["id"], decision="reject", note=n).status_code == 201
    r = client.get(f"/api/boards/{world['watch']}/decisions.csv")
    rows = list(csv.reader(io.StringIO(r.text, newline="")))
    got = [row[6] for row in rows[1:]][::-1]  # oldest first
    assert got == [
        "'=HYPERLINK(\"x\")", "'+1", "'-2", "'@cmd", "'\tTab", "line1\nline2", 'say "hi", ok',
    ]
    assert all(len(row) == 8 for row in rows)
