"""Spark rewrite: change one passage of a text and leave the rest of it as it was."""

from typing import Any

from app.config import get_settings
from app.errors import AppError
from app.providers import get_reasoning
from app.providers.reasoning import strict_schema

REWRITE_SCHEMA: dict[str, Any] = strict_schema(
    {
        "title": "passage_rewrite",
        "type": "object",
        "properties": {"text": {"type": "string"}},
    }
)

PROMPT = """Rewrite one passage of a text.

The full text, for context:
<<<CONTEXT
{context}
CONTEXT>>>

The passage to rewrite:
<<<PASSAGE
{passage}
PASSAGE>>>

Instruction: {instruction}

Return only the rewritten passage as `text`. Keep its language and roughly its length; do not \
repeat the rest of the text."""


def span(text: str, rng: tuple[int, int] | None) -> tuple[int, int]:
    """The passage's [start, end) in `text`: the range clamped to the text, or all of it."""
    if rng is None:
        return 0, len(text)
    start = min(max(rng[0], 0), len(text))
    return start, min(max(rng[1], start), len(text))


def rewrite_passage(text: str, rng: tuple[int, int] | None, instruction: str) -> str:
    """`text` with only `text[start:end]` rewritten by Spark (the whole text when `rng` is None)."""
    start, end = span(text, rng)
    prompt = PROMPT.format(context=text, passage=text[start:end], instruction=instruction.strip())
    out = get_reasoning(get_settings()).structured([], REWRITE_SCHEMA, prompt)
    new = out.get("text") if isinstance(out, dict) else None
    if not isinstance(new, str) or not new.strip():
        raise AppError(502, "REWRITE_EMPTY", "The rewrite came back empty")
    return text[:start] + new + text[end:]
