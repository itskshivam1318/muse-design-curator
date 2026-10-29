"""Board intelligence: aggregate item attributes into signals, tensions and counter-signals."""

import logging
import threading
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any

import numpy as np
from pydantic import BaseModel
from sklearn.cluster import KMeans
from sqlalchemy.orm import Session

from app import events
from app.board.votes import ambiguous_candidates, domain_votes
from app.db.repos import attributes as attrs_repo
from app.db.repos import items as items_repo
from app.db.repos import profiles as profiles_repo
from app.db.session import after_commit
from app.domain.lens import LensSpec
from app.errors import AppError
from app.measure.palette import _NAMED_LAB, _lab_to_hex, delta_e, nearest_color_name
from app.measure.shape import shape_similarity

log = logging.getLogger(__name__)

RELIABLE_CONFIDENCE = 0.7
SIGNAL_MIN_KNOWN = 3
SIGNAL_MIN_CONSISTENCY = 0.6
TENSION_MIN_SHARE = 0.3
MAX_COLOR_CLUSTERS = 3
COLOR_MERGE_DELTA_E = 10.0
SHAPE_SAME = 0.7
COUNTER_MIN_ITEMS = 2
COUNTER_MIN_SHARE_GAP = 0.25
REFERENCE = "reference"
COUNTER = "counter_example"
DISCRETE = ("enum", "ordinal", "boolean")

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


class ColorCluster(BaseModel):
    hex: str
    name: str
    count: int
    share: float


class AttributeProfile(BaseModel):
    key: str
    label: str
    kind: str
    n_known: int
    distribution: dict[str, int] = {}
    modal_value: str | None = None
    consistency: float | None = None
    median: float | None = None
    iqr: float | None = None
    clusters: list[ColorCluster] = []
    medoid_item_id: str | None = None
    values: list[str] = []


class Signal(BaseModel):
    key: str
    label: str
    kind: str
    modal_value: str | None
    consistency: float
    n_known: int


class Tension(BaseModel):
    key: str
    label: str
    values: list[str]
    shares: list[float]


class CounterSignal(BaseModel):
    key: str
    label: str
    value: str
    counter_count: int
    reference_count: int


class DomainVotes(BaseModel):
    votes: dict[str, float] = {}
    mixed: bool = False
    candidates: list[str] | None = None


class BoardProfile(BaseModel):
    n_reference: int = 0
    n_counter: int = 0
    attributes: dict[str, AttributeProfile] = {}
    signals: list[Signal] = []
    tensions: list[Tension] = []
    counter_signals: list[CounterSignal] = []
    centroid: list[float] | None = None
    domain_votes: DomainVotes = DomainVotes()


def _reliable(a: Any) -> bool:
    if not a.enabled or a.value_json is None:
        return False
    return a.confidence >= RELIABLE_CONFIDENCE or a.status in ("edited", "confirmed")


def _token(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _lab_of(a: Any) -> tuple[float, float, float] | None:
    m = a.measured_json
    if isinstance(m, dict) and m.get("lab") and len(m["lab"]) == 3:
        lab = (float(m["lab"][0]), float(m["lab"][1]), float(m["lab"][2]))
        user_set = a.status in ("edited", "confirmed")
        if not user_set or nearest_color_name(lab) == a.value_json:
            return lab  # a user-edited colour name overrides a stale measurement
    return _NAMED_LAB.get(str(a.value_json))


def color_clusters(labs: Sequence[tuple[float, float, float]]) -> list[ColorCluster]:
    """k-means (k <= 3) over Lab colours; clusters closer than dE 10 are merged."""
    if not labs:
        return []
    pts = np.asarray(labs, dtype=float)
    k = min(MAX_COLOR_CLUSTERS, len(np.unique(pts, axis=0)))
    if k <= 1:
        groups = [(pts.mean(axis=0), len(pts))]
    else:
        km = KMeans(n_clusters=k, n_init=4, random_state=0).fit(pts)
        counts = np.bincount(km.labels_, minlength=k)
        groups = [(km.cluster_centers_[i], int(counts[i])) for i in range(k) if counts[i]]
    merged = True
    while merged and len(groups) > 1:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                a, b = groups[i], groups[j]
                if delta_e(tuple(a[0]), tuple(b[0])) < COLOR_MERGE_DELTA_E:  # type: ignore[arg-type]
                    n = a[1] + b[1]
                    groups[i] = ((a[0] * a[1] + b[0] * b[1]) / n, n)
                    del groups[j]
                    merged = True
                    break
            if merged:
                break
    total = sum(n for _, n in groups)
    out = [
        ColorCluster(
            hex=_lab_to_hex(c),
            name=nearest_color_name(tuple(c)),  # type: ignore[arg-type]
            count=n,
            share=round(n / total, 4),
        )
        for c, n in groups
    ]
    return sorted(out, key=lambda c: (-c.count, c.hex))


def _medoid(shapes: list[tuple[str, dict[str, Any]]]) -> tuple[str, float]:
    n = len(shapes)
    sim = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            sim[i, j] = sim[j, i] = shape_similarity(shapes[i][1], shapes[j][1])
    best = int(np.argmax(sim.sum(axis=1)))
    return shapes[best][0], float(np.mean(sim[best] >= SHAPE_SAME))


def _discrete(p: AttributeProfile, tokens: list[str]) -> None:
    dist = Counter(tokens)
    ranked = sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))
    p.distribution = dict(ranked)
    p.modal_value = ranked[0][0]
    p.consistency = round(ranked[0][1] / len(tokens), 4)


def _profile_attribute(
    key: str, label: str, kind: str, spec: Any, rows: list[tuple[str, Any]]
) -> AttributeProfile | None:
    p = AttributeProfile(key=key, label=label, kind=kind, n_known=0)
    if kind in DISCRETE:
        tokens = [_token(a.value_json) for _, a in rows]
        p.n_known = len(tokens)
        if tokens:
            _discrete(p, tokens)
    elif kind == "color":
        labs = [lab for _, a in rows if (lab := _lab_of(a)) is not None]
        p.n_known = len(labs)
        p.clusters = color_clusters(labs)
        if p.clusters:
            p.distribution = {c.hex: c.count for c in p.clusters}
            p.modal_value = p.clusters[0].name
            p.consistency = p.clusters[0].share
    elif kind == "number":
        nums = [float(a.value_json) for _, a in rows if isinstance(a.value_json, int | float)]
        p.n_known = len(nums)
        if nums:
            q1, med, q3 = (float(x) for x in np.percentile(nums, [25, 50, 75]))
            p.median, p.iqr = round(med, 4), round(q3 - q1, 4)
            tol = getattr(spec, "tolerance", None)
            if tol is not None:
                p.consistency = round(sum(abs(v - med) <= tol for v in nums) / len(nums), 4)
    elif kind == "shape":
        shapes = [
            (iid, a.measured_json)
            for iid, a in rows
            if isinstance(a.measured_json, dict) and "hu" in a.measured_json
        ]
        p.n_known = len(shapes)
        if shapes:
            p.medoid_item_id, share = _medoid(shapes)
            p.consistency = round(share, 4)
    elif kind == "text":
        p.values = [str(a.value_json) for _, a in rows]
        p.n_known = len(p.values)
    else:
        return None
    return p


def _centroid(items: Sequence[Any]) -> list[float] | None:
    vecs = []
    for i in items:
        if i.embedding_json:
            v = np.asarray(i.embedding_json, dtype=float)
            n = np.linalg.norm(v)
            if v.ndim == 1 and n > 0:
                vecs.append(v / n)
    if not vecs or len({len(v) for v in vecs}) != 1:
        return None
    mean = np.mean(vecs, axis=0)
    n = np.linalg.norm(mean)
    return [round(float(x), 6) for x in (mean / n if n else mean)]


def _discrete_tokens(kind: str, a: Any) -> str | None:
    if kind in DISCRETE:
        return _token(a.value_json)
    if kind == "color":
        return str(a.value_json)
    return None


def compute_profile(
    items: Sequence[Any],
    attrs_by_item: Mapping[str, Sequence[Any]],
    lens: LensSpec | None,
    votes: Mapping[str, float],
) -> BoardProfile:
    """Pure aggregation of reliable, enabled attribute values. No DB access."""
    items = [
        i for i in items if getattr(i, "kind", None) != "note" and not getattr(i, "staged", False)
    ]
    refs = [i for i in items if i.role == REFERENCE]
    counters = [i for i in items if i.role == COUNTER]
    specs = {a.key: a for a in lens.attributes} if lens else {}

    def collect(group: Sequence[Any]) -> dict[str, list[tuple[str, Any]]]:
        by_key: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for it in group:
            for a in attrs_by_item.get(it.id, ()):
                if _reliable(a) and (not specs or a.key in specs):
                    by_key[a.key].append((it.id, a))
        return by_key

    ref_rows, ctr_rows = collect(refs), collect(counters)
    order = list(specs) if specs else sorted(set(ref_rows) | set(ctr_rows))

    attributes: dict[str, AttributeProfile] = {}
    for key in order:
        rows = ref_rows.get(key, [])
        spec = specs.get(key)
        first = rows[0][1] if rows else None
        kind = spec.kind if spec else (first.kind if first else None)
        label = spec.label if spec else (getattr(first, "label", key) if first else key)
        if kind is None:
            continue
        p = _profile_attribute(key, label, kind, spec, rows)
        if p is not None and p.n_known:
            attributes[key] = p

    signals = [
        Signal(
            key=p.key,
            label=p.label,
            kind=p.kind,
            modal_value=p.modal_value,
            consistency=p.consistency,
            n_known=p.n_known,
        )
        for p in attributes.values()
        if p.kind != "text"
        and p.consistency is not None
        and p.n_known >= SIGNAL_MIN_KNOWN
        and p.consistency >= SIGNAL_MIN_CONSISTENCY
    ]
    signals.sort(key=lambda s: (-s.consistency, s.key))

    tensions: list[Tension] = []
    for p in attributes.values():
        shares: list[tuple[str, float]]
        if p.kind in DISCRETE:
            shares = [(v, c / p.n_known) for v, c in p.distribution.items()]
        elif p.kind == "color":
            shares = [(c.name, c.share) for c in p.clusters]
        else:
            continue
        if (
            len(shares) >= 2
            and shares[0][1] >= TENSION_MIN_SHARE
            and shares[1][1] >= TENSION_MIN_SHARE
        ):
            tensions.append(
                Tension(
                    key=p.key,
                    label=p.label,
                    values=[shares[0][0], shares[1][0]],
                    shares=[round(shares[0][1], 4), round(shares[1][1], 4)],
                )
            )

    counter_signals: list[CounterSignal] = []
    for key in order:
        spec = specs.get(key)
        for rows_c in [ctr_rows.get(key, [])]:
            kind = spec.kind if spec else (rows_c[0][1].kind if rows_c else "")
            ctr = Counter(t for _, a in rows_c if (t := _discrete_tokens(kind, a)) is not None)
            ref = Counter(
                t for _, a in ref_rows.get(key, []) if (t := _discrete_tokens(kind, a)) is not None
            )
            n_ctr, n_ref = sum(ctr.values()), sum(ref.values())
            for value, n in sorted(ctr.items()):
                ref_share = ref.get(value, 0) / n_ref if n_ref else 0.0
                if n >= COUNTER_MIN_ITEMS and n / n_ctr - ref_share >= COUNTER_MIN_SHARE_GAP:
                    counter_signals.append(
                        CounterSignal(
                            key=key,
                            label=spec.label if spec else key,
                            value=value,
                            counter_count=n,
                            reference_count=ref.get(value, 0),
                        )
                    )

    cands = ambiguous_candidates(dict(votes))
    return BoardProfile(
        n_reference=len(refs),
        n_counter=len(counters),
        attributes=attributes,
        signals=signals,
        tensions=tensions,
        counter_signals=counter_signals,
        centroid=_centroid(refs),
        domain_votes=DomainVotes(
            votes={d: round(v, 4) for d, v in votes.items()},
            mixed=cands is not None,
            candidates=cands,
        ),
    )


def recompute(session: Session, board_id: str) -> int | None:
    """Load the board, compute its profile and save a new version only if it changed.

    Returns the new version, or None when nothing changed. `profile.updated` is published
    after the caller's transaction commits.
    """
    from app.lens_service import auto_attach_domain, ensure_board_lens

    with _locks[board_id]:
        auto_attach_domain(session, board_id)
        try:
            lens = ensure_board_lens(session, board_id)
        except AppError:
            lens = None
        items = items_repo.list_active(session, board_id, include_staged=False)
        attrs = {i.id: attrs_repo.for_item(session, i.id) for i in items}
        refs = [i for i in items if i.role == REFERENCE]
        profile = compute_profile(items, attrs, lens, domain_votes(session, refs))
        data = profile.model_dump(mode="json")
        current = profiles_repo.latest(session, board_id)
        if current is not None and current.profile_json == data:
            return None
        version = profiles_repo.save(session, board_id, data)
        after_commit(
            session,
            partial(
                events.publish, board_id, "profile.updated", {"version": version, "profile": data}
            ),
        )
        return version
