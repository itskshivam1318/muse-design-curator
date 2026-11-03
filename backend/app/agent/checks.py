"""The checks `finish` runs before a run may end: every deliverable has items that are still on the
board and passed their result check, then the output images read as one design."""

from collections.abc import Sequence
from typing import Any

from app.config import get_settings
from app.providers import get_reasoning
from app.providers.reasoning import MAX_STRUCTURED_IMAGES
from app.providers.reliability import ModelError

CONSISTENCY_SCHEMA: dict[str, Any] = {
    "title": "output_consistency",
    "type": "object",
    "properties": {
        "one_design": {"type": "boolean"},
        "outliers": {"type": "array", "items": {"type": "integer"}},
        "reason": {"type": "string"},
    },
}


class CheckUnavailable(Exception):
    """The consistency check could not get an answer from the model; worth trying again."""


def check_passed(check: dict[str, Any] | None) -> bool | None:
    """True/False for an item's result check, None when it was never checked (not blocking).

    Explore render: the target answer is "yes" and nothing drifted. Note render: `target_ok` is
    True (an unclear answer is None, which fails). Any `error` fails."""
    if not isinstance(check, dict) or not check:
        return None
    if "error" in check:
        return False
    if "target" in check:
        target = check.get("target")
        answer = target.get("answer") if isinstance(target, dict) else None
        return answer == "yes" and check.get("drifted") == []
    if "target_ok" in check:
        return check["target_ok"] is True
    return None


def _why_failed(check: dict[str, Any]) -> str:
    if "error" in check:
        return f"error: {check['error']}"
    if "target" in check:
        drifted = check.get("drifted") or []
        if drifted:
            return "drifted: " + ", ".join(str(k) for k in drifted)
        target = check.get("target")
        answer = target.get("answer") if isinstance(target, dict) else None
        return f"target: {answer or 'unclear'}"
    return f"answer: {check.get('answer') or 'unclear'}"


def output_item_ids(run: dict[str, Any]) -> list[str]:
    """The items on the run's output sheet, in sheet order, each once."""
    output = run.get("output") or {}
    seen: list[str] = []
    for section in output.get("sections") or []:
        for entry in section.get("items") or []:
            if entry["item_id"] not in seen:
                seen.append(entry["item_id"])
    return seen


def deliverable_problems(run: dict[str, Any], items_by_id: dict[str, dict[str, Any]]) -> list[str]:
    """What stops the output from delivering the goal, one sentence each: a deliverable with no
    item, an output item no longer on the board, an output item whose result check failed.

    `run` is `run_to_dict`'s shape; `items_by_id` the board's live items."""
    output = run.get("output") or {}
    sections = output.get("sections") or []
    filled = {s["deliverable"] for s in sections if s.get("items")}
    problems = [f"'{d}' has no item" for d in run["deliverables"] if d not in filled]
    for item_id in output_item_ids(run):
        item = items_by_id.get(item_id)
        if item is None:
            problems.append(f"{item_id} was removed from the board")
        elif check_passed(item.get("check")) is False:
            problems.append(f"{item_id} failed its result check ({_why_failed(item['check'])})")
    return problems


def _prompt(count: int, goal: str) -> str:
    return (
        f"These {count} images are the output of one piece of design work. The goal: {goal}\n"
        "Do they all show one design: the same object or space, seen in different views, "
        "details or states? Set one_design to true if they do. If not, list in outliers the "
        "0-based indexes of the images that show a different design from the rest, and say "
        "briefly in reason what differs."
    )


def consistency_problems(
    images: list[bytes], goal: str, item_ids: Sequence[str] | None = None
) -> list[str]:
    """[] when the images read as one design, else one problem per outlier (named by its item id
    from `item_ids`, else by its position) with the model's reason. Blocking: one model call on
    at most the first 12 images. Raises `CheckUnavailable` when the model gives no usable answer
    (that says nothing about the output)."""
    images = images[:MAX_STRUCTURED_IMAGES]
    names = list(item_ids or [])[: len(images)]
    names += [f"image {i + 1}" for i in range(len(names), len(images))]
    try:
        answer = get_reasoning(get_settings()).structured(
            images, CONSISTENCY_SCHEMA, _prompt(len(images), goal)
        )
    except ModelError as e:
        raise CheckUnavailable(e.code) from e
    if not isinstance(answer, dict):
        raise CheckUnavailable("BAD_ANSWER")
    if answer.get("one_design") is True:
        return []
    reason = " ".join(str(answer.get("reason") or "").split()) or "no reason given"
    outliers: list[int] = []
    raw = answer.get("outliers")
    for i in raw if isinstance(raw, list) else []:
        valid = isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(names)
        if valid and i not in outliers:
            outliers.append(i)
    if not outliers:
        return [f"the output does not show one design: {reason}"]
    return [f"{names[i]} does not show the same design as the rest: {reason}" for i in outliers]
