from typing import Any

from app.agent import run_state
from app.agent.context import ToolContext, api_error, board_items, require_option

SHEET_GAP = 80  # between the board's bounding box and the sheet
ITEM_H = 320  # every item on the sheet is scaled to this height
GAP = 24  # between notes and items along a row
ROW_GAP = 40  # between rows (and under the title)
TITLE_W, TITLE_H = 600, 80
LABEL_W, LABEL_H = 220, 120
CAPTION_GAP, CAPTION_H, CAPTION_MIN_W = 12, 100, 160
TITLE_MAX = 200
WHY_MAX = 2000

DEFINITION = {
    "name": "compose_output",
    "description": "Lay out the run's output sheet to the right of the board: a title, then one "
    "row per deliverable with its items in order, each captioned with why it is there. Items are "
    "moved onto the sheet and scaled to one height. Calling it again replaces the sheet. Every "
    "deliverable named here must be one of the run's.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": f"Up to {TITLE_MAX} characters."},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "deliverable": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "item_id": {"type": "string"},
                                    "why": {"type": "string", "description": "The caption."},
                                },
                                "required": ["item_id", "why"],
                            },
                        },
                        "contrast": {
                            "type": "boolean",
                            "default": False,
                            "description": "A deliberate counter-example (a not-this): its items "
                            "are checked like the rest but left out of the one-design comparison.",
                        },
                    },
                    "required": ["deliverable", "items"],
                },
            },
        },
        "required": ["title", "sections"],
    },
}


class _Refused(Exception):
    def __init__(self, error: dict[str, Any]) -> None:
        self.error = error


def _bad(message: str) -> dict[str, Any]:
    return {"error": "BAD_SECTIONS", "message": message}


def _sections(raw: Any) -> list[dict[str, Any]] | dict[str, Any]:
    if not isinstance(raw, list):
        return _bad("sections is a list of {deliverable, items}.")
    out = []
    for section in raw:
        if not isinstance(section, dict) or not isinstance(section.get("deliverable"), str):
            return _bad("Each section has a deliverable name and a list of items.")
        entries = section.get("items")
        if not isinstance(entries, list):
            return _bad("Each section has a deliverable name and a list of items.")
        items = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_id"), str):
                return _bad("Each item is {item_id, why}.")
            why = entry.get("why")
            items.append(
                {
                    "item_id": entry["item_id"],
                    "why": (why.strip() if isinstance(why, str) else "")[:WHY_MAX],
                }
            )
        kept: dict[str, Any] = {"deliverable": section["deliverable"].strip(), "items": items}
        if section.get("contrast") is True:
            kept["contrast"] = True
        out.append(kept)
    return out


def _validate(
    sections: list[dict[str, Any]], run: dict[str, Any], live: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    names = [s["deliverable"] for s in sections]
    for name in names:
        if name not in run["deliverables"]:
            return {
                "error": "UNKNOWN_DELIVERABLE",
                "message": f"{name!r} is not a deliverable of this run; they are: "
                + ", ".join(repr(d) for d in run["deliverables"]),
            }
    if len(set(names)) != len(names):
        return _bad("Each deliverable gets one section.")
    seen: set[str] = set()
    for section in sections:
        for entry in section["items"]:
            item_id = entry["item_id"]
            if item_id not in live:
                return {
                    "error": "ITEM_NOT_ON_BOARD",
                    "message": f"{item_id} is not on the open board.",
                }
            if item_id in seen:
                return {"error": "DUPLICATE_ITEM", "message": f"{item_id} is on the sheet twice."}
            seen.add(item_id)
    return None


async def _undock(ctx: ToolContext, item: dict[str, Any]) -> None:
    """A kept explore take is drawn in its option's ring, wherever the item says it is, until
    it is undocked; undock it so the sheet's position holds (as dragging it out would)."""
    option_id = item.get("explore_option_id")
    if not option_id:
        return
    option = await require_option(ctx, option_id)
    if "error" in option or option.get("kept_item_id") != item["id"] or option.get("undocked"):
        return
    status, res = await ctx.api.patch(f"/api/options/{option_id}", json={"undocked": True})
    if status != 200:
        raise _Refused(api_error(status, res))


async def _note(ctx: ToolContext, text: str, x: float, y: float, w: float, h: float) -> str:
    body = {"text": text, "x": x, "y": y, "w": w, "h": h}
    status, res = await ctx.api.post(f"/api/boards/{ctx.board_id}/notes", json=body)
    if status != 201:
        raise _Refused(api_error(status, res))
    return str(res["id"])


async def _lay_out(
    ctx: ToolContext,
    title: str,
    sections: list[dict[str, Any]],
    live: dict[str, dict[str, Any]],
    origin: tuple[float, float],
    note_ids: list[str],
) -> None:
    left, top = origin
    note_ids.append(await _note(ctx, title, left, top, TITLE_W, TITLE_H))
    y = top + TITLE_H + ROW_GAP
    for section in sections:
        note_ids.append(await _note(ctx, section["deliverable"], left, y, LABEL_W, LABEL_H))
        x = left + LABEL_W + GAP
        for entry in section["items"]:
            item = live[entry["item_id"]]
            await _undock(ctx, item)
            w = item["w"] * ITEM_H / item["h"] if item["h"] else ITEM_H
            status, res = await ctx.api.patch(
                f"/api/items/{item['id']}", json={"x": x, "y": y, "w": w, "h": ITEM_H}
            )
            if status != 200:
                raise _Refused(api_error(status, res))
            if entry["why"]:
                caption_w = max(w, CAPTION_MIN_W)
                note_ids.append(
                    await _note(
                        ctx, entry["why"], x, y + ITEM_H + CAPTION_GAP, caption_w, CAPTION_H
                    )
                )
            x += max(w, CAPTION_MIN_W) + GAP
        y += ITEM_H + CAPTION_GAP + CAPTION_H + ROW_GAP


def _origin(rest: list[dict[str, Any]]) -> tuple[float, float]:
    """Right of the bounding box of everything not going on the new sheet (an item the previous
    sheet held but this one drops counts, so the new sheet clears it), top-aligned with it."""
    if not rest:
        return 0.0, 0.0
    return (
        float(max(i["x"] + i["w"] for i in rest) + SHEET_GAP),
        float(min(i["y"] for i in rest)),
    )


async def run(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    title = args.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if not 0 < len(title) <= TITLE_MAX:
        return {"error": "BAD_TITLE", "message": f"The title is 1 to {TITLE_MAX} characters."}
    sections = _sections(args.get("sections"))
    if isinstance(sections, dict):
        return sections
    assert ctx.board_id is not None
    current = await run_state.current(ctx.board_id, ctx.run_id)
    if current is None:
        return run_state.no_run()
    ctx.run_id = current["id"]

    items = await board_items(ctx)
    if isinstance(items, dict):
        return items
    old_notes = set((current["output"] or {}).get("note_ids") or [])
    live = {i["id"]: i for i in items if i["id"] not in old_notes}
    refused = _validate(sections, current, live)
    if refused is not None:
        return refused

    for note_id in old_notes:  # the previous sheet's notes; one the person removed is gone already
        status, res = await ctx.api.delete(f"/api/items/{note_id}")
        if status not in (204, 404):
            return api_error(status, res)
    on_sheet = {e["item_id"] for section in sections for e in section["items"]}
    origin = _origin([i for i in live.values() if i["id"] not in on_sheet])
    note_ids: list[str] = []
    try:
        await _lay_out(ctx, title, sections, live, origin, note_ids)
    except _Refused as refusal:
        for note_id in note_ids:
            await ctx.api.delete(f"/api/items/{note_id}")
        await run_state.update(current["id"], output_json=None)
        return refusal.error
    output = {"title": title, "sections": sections, "note_ids": note_ids}
    await run_state.update(current["id"], output_json=output)
    placed = [e["item_id"] for s in sections for e in s["items"]]
    return {"run_id": current["id"], "title": title, "note_ids": note_ids, "item_ids": placed}
