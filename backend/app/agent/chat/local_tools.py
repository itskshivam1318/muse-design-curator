"""Chat-only tools, run by the loop rather than the registry: `ask_user` and `confirm_part`
suspend the turn for the person's answer; `look_at` shows the model pictures."""

from __future__ import annotations

from typing import Any

from app.agent.context import ApiClient
from app.providers.meta_client import data_url

__all__ = ["DEFINITIONS", "LOOK_MAX", "NAMES", "SUSPENDING", "look_at_images", "valid_args"]

LOOK_MAX = 6

DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "ask_user",
        "description": "Ask the person a question and wait for the answer. Pass choices when "
        "the answer is one of a few: item ids (shown as picture buttons) or short text options.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Item ids or short text options.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "confirm_part",
        "description": "Show the person a part's region on its picture and ask whether it is "
        "right. The answer is a yes, a box they drew ([x0, y0, x1, y1] fractions) where the part "
        "really is, or their words.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "part": {"type": "string", "description": "The part's key."},
                "why": {
                    "type": "string",
                    "description": "The question shown to the person: what you need confirmed.",
                },
            },
            "required": ["item_id", "part", "why"],
        },
    },
    {
        "name": "look_at",
        "description": f"See up to {LOOK_MAX} pictures on the board; they come in the next "
        "input as images.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": LOOK_MAX,
                }
            },
            "required": ["item_ids"],
        },
    },
]

NAMES = {d["name"] for d in DEFINITIONS}
SUSPENDING = {"ask_user", "confirm_part"}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _texts(value: Any) -> bool:
    return isinstance(value, list) and all(_text(v) for v in value)


def valid_args(name: str, args: dict[str, Any]) -> bool:
    """Whether a chat-only tool's arguments are usable as given."""
    if args.get("_bad_arguments"):
        return False
    if name == "ask_user":
        return _text(args.get("question")) and (
            args.get("choices") is None or _texts(args["choices"])
        )
    if name == "confirm_part":
        return all(_text(args.get(k)) for k in ("item_id", "part", "why"))
    if name == "look_at":
        ids = args.get("item_ids")
        return isinstance(ids, list) and _texts(ids) and 1 <= len(ids) <= LOOK_MAX
    return False


async def look_at_images(
    api: ApiClient, item_ids: list[str]
) -> tuple[dict[str, Any] | None, list[str]]:
    """The user item carrying the pictures (None when none could be read), and the ids missed.
    The item starts with a text part, so it never empties when old images are dropped."""
    images: list[dict[str, Any]] = []
    shown: list[str] = []
    missing: list[str] = []
    for item_id in item_ids:
        data = await api.get_bytes(f"/api/items/{item_id}/image")
        if data is None:
            missing.append(item_id)
            continue
        shown.append(item_id)
        images.append({"type": "input_image", "image_url": data_url(data)})
    if not images:
        return None, missing
    intro = {"type": "input_text", "text": f"The pictures you asked to look at: {', '.join(shown)}"}
    return {"role": "user", "content": [intro, *images]}, missing
