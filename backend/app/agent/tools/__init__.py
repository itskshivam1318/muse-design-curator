"""The tool registry. Each tool is one module in this package with:

- `DEFINITION: dict` — `name`, `description`, `parameters` (JSON schema, without `say` and
  `highlight`: the registry adds both to every tool);
- `async def run(ctx: ToolContext, args: dict) -> dict` — returns a result, or a refusal
  `{"error": CODE, "message": ...}`; a result may carry `"item_ids"` for the panel to focus;
- optionally `MCP_ONLY = True` (offered only over MCP) and `NEEDS_BOARD = False` (default True).

Add a tool by importing its module into `_MODULES`.
"""

import copy
import logging
from types import ModuleType
from typing import Any

from app.agent import steps
from app.agent.context import ToolContext
from app.agent.tools import (
    add_dimension,
    add_note,
    add_reference,
    analyse,
    create_board,
    explore,
    get_analysis,
    keep_option,
    list_boards,
    move_item,
    open_board,
    propose_lens,
    read_board,
    remove_item,
    run_plugin,
    set_lens,
    unkeep_option,
    upload_reference,
    visualize_note,
    visualize_option,
    wait,
)

log = logging.getLogger(__name__)

SAY_MAX = 200

_MODULES: tuple[ModuleType, ...] = (
    add_dimension,
    add_note,
    add_reference,
    analyse,
    create_board,
    explore,
    get_analysis,
    keep_option,
    list_boards,
    move_item,
    open_board,
    propose_lens,
    read_board,
    remove_item,
    run_plugin,
    set_lens,
    unkeep_option,
    upload_reference,
    visualize_note,
    visualize_option,
    wait,
)

TOOLS: dict[str, ModuleType] = {m.DEFINITION["name"]: m for m in _MODULES}

_COMMON_PARAMS: dict[str, Any] = {
    "say": {
        "type": "string",
        "description": f"One sentence for the person following along: what you are doing and why "
        f"(at most {SAY_MAX} characters).",
    },
    "highlight": {
        "type": "boolean",
        "default": False,
        "description": "Mark this step as a highlight of the run.",
    },
}


def definitions(source: str) -> list[dict[str, Any]]:
    """Tool definitions offered to `source` ("mcp" or "muse"), each with `say` and `highlight`."""
    out = []
    for module in TOOLS.values():
        if getattr(module, "MCP_ONLY", False) and source != "mcp":
            continue
        definition = copy.deepcopy(module.DEFINITION)
        params = definition.setdefault("parameters", {"type": "object"})
        params.setdefault("properties", {}).update(copy.deepcopy(_COMMON_PARAMS))
        out.append(definition)
    return out


def _say(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:SAY_MAX] or None


async def run_tool(ctx: ToolContext, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Run a tool by name; never raises. With a run open, the call is recorded as a step."""
    module = TOOLS.get(name)
    if module is None:
        return {"error": "UNKNOWN_TOOL", "message": f"There is no tool named {name!r}."}
    if getattr(module, "NEEDS_BOARD", True) and ctx.board_id is None:
        return {"error": "NO_BOARD_OPEN", "message": "Open a board first."}

    args = dict(args or {})
    say = _say(args.pop("say", None))
    highlight = bool(args.pop("highlight", False))
    try:
        result: dict[str, Any] = await module.run(ctx, args)
    except Exception as e:
        log.exception("agent tool %s failed", name)
        result = {"error": "TOOL_FAILED", "message": str(e)}

    run_id = ctx.run_id  # read after the call: a tool may have opened the run
    if run_id is not None:
        try:
            await steps.record(run_id, name, args, say, highlight, result)
        except Exception:
            log.exception("could not record agent step for %s", name)
    return result
