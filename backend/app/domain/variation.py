"""Variation request: vary exactly one target attribute while protecting others."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.board.profile import BoardProfile
from app.domain.attributes import AttributeRecord, Value, canonical_token, validate_value
from app.domain.kinds import AttributeSpec
from app.domain.lens import LensSpec
from app.errors import AppError
from app.measure.palette import color_names

Mode = Literal["explore", "prefer", "avoid", "nudge"]


class Nudge(BaseModel):
    direction: Literal["more", "less"]
    steps: Literal[1, 2] = 1


class VariationRequest(BaseModel):
    source_item_id: str
    target_key: str
    mode: Mode
    target_values: list[str] = []
    protected_keys: list[str] = []
    nudge: Nudge | None = None


class ProtectedSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    spec: AttributeSpec
    value: Value


class VariationSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    request: VariationRequest
    target_spec: AttributeSpec
    target_value: Value = None
    values: tuple[Value, ...] = ()
    protected: tuple[ProtectedSpec, ...] = Field(default=())


class _HasRole(Protocol):
    role: str


def _err(code: str, message: str, **details: Any) -> AppError:
    return AppError(422, code, message, details)


def _clean_value(raw: str, spec: AttributeSpec) -> Value:
    if spec.kind == "color":
        token = canonical_token(raw)
        return token if token in color_names() else None
    return validate_value(raw, spec)


def number_step(spec: AttributeSpec) -> float:
    return 2 * spec.tolerance  # type: ignore[union-attr]


def validate_variation(
    req: VariationRequest,
    item: _HasRole,
    attrs: Sequence[AttributeRecord],
    lens: LensSpec,
) -> VariationSpec:
    key = req.target_key
    # 1. params shape
    if req.mode == "nudge":
        if req.nudge is None:
            raise _err(
                "NUDGE_PARAMS_REQUIRED", "A nudge needs a direction and step count.", key=key
            )
    elif req.nudge is not None:
        raise _err(
            "NUDGE_PARAMS_REQUIRED",
            f"Nudge settings only apply to the nudge mode, not {req.mode}.",
            key=key,
        )
    if req.mode in ("explore", "nudge") and req.target_values:
        raise _err(
            "TARGET_VALUES_NOT_ALLOWED", f"The {req.mode} mode takes no target values.", key=key
        )
    if req.mode in ("prefer", "avoid") and not req.target_values:
        raise _err(
            "TARGET_VALUES_REQUIRED",
            f"The {req.mode} mode needs at least one target value.",
            key=key,
        )

    # 2. source role
    if item.role == "counter_example":
        raise _err(
            "SOURCE_IS_COUNTER_EXAMPLE",
            "A counter-example cannot be the source of a variation.",
            source_item_id=req.source_item_id,
        )

    # 3. keys in lens
    specs = {a.key: a for a in lens.attributes}
    for k in [key, *req.protected_keys]:
        if k not in specs:
            raise _err("UNKNOWN_ATTRIBUTE", f"{k} is not an attribute of this board's lens.", key=k)
    seen: set[str] = set()
    for k in req.protected_keys:
        if k in seen:
            raise _err(
                "DUPLICATE_PROTECTED_KEY",
                f"{specs[k].label} is listed as protected more than once.",
                key=k,
            )
        seen.add(k)
    tspec = specs[key]
    if key in seen:
        raise _err(
            "TARGET_PROTECTED_CONFLICT",
            f"{tspec.label} cannot be both the target and protected.",
            key=key,
        )

    by_key = {a.key: a for a in attrs}
    # 4. disabled
    trec = by_key.get(key)
    if trec is not None and not trec.enabled:
        raise _err("TARGET_DISABLED", f"{tspec.label} is disabled and cannot be varied.", key=key)
    for k in req.protected_keys:
        rec = by_key.get(k)
        if rec is not None and not rec.enabled:
            raise _err(
                "PROTECTED_DISABLED",
                f"{specs[k].label} is disabled and cannot be protected.",
                key=k,
            )

    # 5. value checks
    current = trec.value if trec is not None else None
    values: list[Value] = []
    for raw in req.target_values:
        cleaned = _clean_value(raw, tspec)
        if cleaned is None:
            raise _err(
                "TARGET_VALUE_INVALID",
                f"{raw!r} is not a valid value for {tspec.label}.",
                key=key,
                value=raw,
            )
        values.append(cleaned)
    if req.mode == "prefer" and current is not None and len(values) == 1 and values[0] == current:
        raise _err("PREFER_EQUALS_CURRENT", f"The source already has that {tspec.label}.", key=key)

    # 6. known-value checks
    if req.mode == "explore" and current is None:
        raise _err(
            "EXPLORE_NEEDS_KNOWN_TARGET",
            f"The source item has no known {tspec.label} to explore from.",
            key=key,
        )
    protected: list[ProtectedSpec] = []
    for k in req.protected_keys:
        rec = by_key.get(k)
        if rec is None or rec.value is None:
            raise _err(
                "PROTECTED_VALUE_UNKNOWN", f"{specs[k].label} has no known value to protect.", key=k
            )
        protected.append(ProtectedSpec(key=k, spec=specs[k], value=rec.value))

    # 7. nudge
    if req.mode == "nudge":
        assert req.nudge is not None
        if tspec.kind not in ("ordinal", "number"):
            raise _err(
                "NUDGE_NOT_SUPPORTED",
                f"{tspec.label} cannot be nudged; only ordinal and number attributes can.",
                key=key,
            )
        if current is None:
            raise _err(
                "NUDGE_NEEDS_KNOWN_TARGET",
                f"The source item has no known {tspec.label} to nudge.",
                key=key,
            )
        sign = 1 if req.nudge.direction == "more" else -1
        if tspec.kind == "ordinal":
            if str(current) not in tspec.scale:
                raise _err(
                    "NUDGE_NEEDS_KNOWN_TARGET",
                    f"The source item's {tspec.label} is not a step on its scale.",
                    key=key,
                )
            idx = tspec.scale.index(str(current)) + sign * req.nudge.steps
            ok = 0 <= idx < len(tspec.scale)
        else:
            new = float(current) + sign * req.nudge.steps * number_step(tspec)  # type: ignore[arg-type]
            ok = tspec.min <= new <= tspec.max
        if not ok:
            raise _err(
                "NUDGE_OUT_OF_RANGE",
                f"Nudging {tspec.label} {req.nudge.direction} by {req.nudge.steps} goes beyond its range.",
                key=key,
            )

    return VariationSpec(
        request=req,
        target_spec=tspec,
        target_value=current,
        values=tuple(values),
        protected=tuple(protected),
    )


SIGNAL_MIN_CONSISTENCY = 0.6
SIGNAL_MIN_KNOWN = 3
PRESELECT_MIN = 3  # same-part attributes top the default protections up to this many


def propose_protected(
    attrs: Sequence[AttributeRecord], target_key: str, profile: BoardProfile | None
) -> list[dict[str, Any]]:
    """Every enabled, known, non-target attribute as a protection chip, with its default state.

    Pre-selected: board signals (consistency >= 0.6, n_known >= 3), values the user edited or
    confirmed, and, while that gives fewer than 3, the next same-part attributes in lens order.
    The frontend mirrors this (`vary/logic.ts`); the shared fixture keeps them in step.
    """
    strength = {
        s.key: s.consistency
        for s in (profile.signals if profile else [])
        if s.consistency >= SIGNAL_MIN_CONSISTENCY and s.n_known >= SIGNAL_MIN_KNOWN
    }
    target = next((a for a in attrs if a.key == target_key), None)
    part = target.part if target else None
    rows: list[dict[str, Any]] = []
    for a in attrs:
        if not a.enabled or a.value is None or a.key == target_key:
            continue
        reason = (
            "board_signal"
            if a.key in strength
            else "user_confirmed" if a.status in ("edited", "confirmed") else "suggested"
        )
        rows.append(
            {
                "key": a.key,
                "is_board_signal": a.key in strength,
                "strength": float(strength.get(a.key, 0.0)),
                "preselected": reason != "suggested",
                "reason": reason,
                "_part": a.part,
            }
        )
    chosen = sum(1 for r in rows if r["preselected"])
    if part is not None:
        for r in rows:
            if chosen >= PRESELECT_MIN:
                break
            if not r["preselected"] and r["_part"] == part:
                r["preselected"], r["reason"] = True, "same_part"
                chosen += 1
    for r in rows:
        del r["_part"]
    rows.sort(
        key=lambda r: (not r["is_board_signal"], -float(r["strength"]))
    )  # stable: keeps lens order
    return rows
