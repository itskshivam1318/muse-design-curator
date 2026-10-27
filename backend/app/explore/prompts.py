"""Prompts for exploring an attribute into named design moves and for checking the result."""

from typing import Any, Literal

from app.domain.attributes import AttributeRecord, Value
from app.domain.kinds import AttributeSpec, EnumSpec, NumberSpec, OrdinalSpec


def _show(value: Value) -> str:
    return "unknown (not read from this image)" if value is None else str(value)


def _value_rule(spec: AttributeSpec) -> str:
    if isinstance(spec, EnumSpec):
        listed = ", ".join(spec.vocabulary or [])
        rule = "`value` is a short snake_case token naming the option (for example contrasting_accent)."
        if listed:
            rule += (
                f" Known values for this attribute: {listed}. They are inspiration, not a limit:"
                " options may go beyond them, and `value` may be a new token."
                " This is not a list to repeat; do not just list these values back."
            )
        return rule
    if isinstance(spec, OrdinalSpec):
        return (
            f"`value` must be exactly one step of the scale: {', '.join(spec.scale)}."
            " Options should still be distinct, nameable moves, not just the step names."
        )
    if isinstance(spec, NumberSpec):
        return (
            f"`value` is a number as a string, between {spec.min:g} and {spec.max:g} {spec.unit}."
        )
    if spec.kind == "boolean":
        return (
            '`value` is "true" or "false" and stays the current state. Options are about'
            " how the feature is done (for example where it sits, its size, how it is framed)."
        )
    if spec.kind == "color":
        return "`value` is a plain colour name (for example burnt orange)."
    return "`value` is a short snake_case token naming the option."


def _attribute_lines(attributes: list[AttributeRecord]) -> str:
    return "\n".join(f"- {a.key} ({a.label}): {_show(a.value)}" for a in attributes) or "- none"


def build_explore_prompt(
    *,
    spec: AttributeSpec,
    current: Value,
    attributes: list[AttributeRecord],
    board_title: str,
    board_context: str,
    existing_names: list[str],
    parent: dict[str, Any] | None,
    steer: str | None,
    mode: Literal["initial", "more", "further"],
) -> str:
    parts = [
        (
            "You are a design collaborator. Look at the image and propose 6 to 10 options for how"
            f' its "{spec.label}" ({spec.key}) could be different.'
        ),
        f"Board: {board_title}." + (f" Context: {board_context}" if board_context else ""),
        f"Current {spec.label}: {_show(current)}.",
        (
            "Each option is a specific, nameable design move grounded in THIS image and this"
            ' board, something a designer could say in a few words (for example "a contrasting'
            ' accent", "a single-material version", "pared back to one element"). Never answer'
            " with generic vocabulary words."
        ),
        (
            "Fields: `name` is short and human; `description` is one line on what it looks like"
            " on this item; `distance` is near (a small step from the current), bold, or wild;"
            " `edit_prompt` is a one-sentence instruction to an image editor that changes only"
            f" this attribute; {_value_rule(spec)}"
        ),
        "`keeps` lists the attribute keys this option assumes stay the same. Use only keys from"
        " this list of the item's attributes:\n" + _attribute_lines(attributes),
        "Mix distances: some near, some bold, a few wild.",
    ]
    if parent:
        parts.append(
            f'Go deeper on this option: "{parent.get("name")}" ({parent.get("distance")}):'
            f" {parent.get('description')}. Propose sub-options that are variations or"
            " refinements of it, not of the original."
        )
    if mode == "further":
        parts.append(
            "Go bolder: push further from the current value than the options already given."
            " Favour bold and wild."
        )
    if existing_names:
        parts.append(
            "Options already given (do not repeat these or close variants): "
            + "; ".join(existing_names)
        )
    if steer:
        parts.append(f"Direction from the user: {steer}")
    return "\n\n".join(parts)


def build_check_prompt(*, label: str, option_name: str, description: str) -> str:
    return (
        f'Look at the image. Does it show this for its {label}: "{option_name}"'
        f" ({description})?\n"
        "Answer `yes`, `no`, or `unclear` with a confidence from 0 to 1. If you can find the"
        " part that answers it, give `box` as [x0, y0, x1, y1] in 0..1 image coordinates,"
        " otherwise null. `note` is one short sentence on what you see."
    )
