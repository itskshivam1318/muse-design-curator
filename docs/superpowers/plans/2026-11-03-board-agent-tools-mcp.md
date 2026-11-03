# Board agent, part 1: board tools, MCP, steps, goal, agent panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code (or Muse Code) connects to Muse over MCP, works a board toward a goal with
one recorded, narrated step per tool call, ends with a code-checked output sheet, and the person
watches every change and step land live on the open board.

**Architecture:** A tool registry in `backend/app/agent/` (one file per tool: `DEFINITION` +
`async run(ctx, args)`). Tools call the app's **own REST API in-process** through
`httpx.AsyncClient(transport=ASGITransport(app))`, so validation, the demo lock and every board
event behave exactly as when a person clicks. `run_tool` records each call as an `AgentStep` and
publishes `agent.step` on the board's SSE. An MCP server (official `mcp` SDK, streamable HTTP) is
mounted at `/mcp` inside the FastAPI app and serves the registry. The existing bottom-right
`AgentCard` becomes the live agent panel.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic (SQLite), httpx, `mcp` Python SDK (2.x), pytest;
React + React Query + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-board-agent-design.md`. This plan covers the spec's
build order steps 1–3 (sections 1, 2, 3, 4 "Agent panel"). **Not in this plan** (later plans):
`render_view` and the second image provider; `search_references` and the in-app Muse agent loop;
`put_into` (waits for the put-into plan); spotlight replay; board export/import and the landing
page; recording the four boards.

## Global Constraints

- Python 3.12, ruff line length 100, mypy clean; frontend `npm run lint`, `tsc`, Vitest green.
- Tools never raise to their caller: a refused call returns `{"error": "<CODE>", "message": "..."}`.
- Every tool accepts an optional `say: str` (one sentence, ≤ 200 chars, trimmed); it is stored on
  the step and shown in the panel. `highlight: bool` (default false) is accepted on every tool too.
- Tool calls go through the REST API in-process; no tool writes the DB directly except the
  agent-run/step tables owned by this plan.
- `MCP_ENABLED` (default `False`) gates `/mcp`; when off, `/mcp` is 404.
- With `DEMO_MODE` on and locked, write tools are refused by the existing demo guard (the in-process
  client carries no unlock cookie); the tool returns that refusal as its error.
- Result check "passed" (used by `finish`): explore render → `check.target.answer == "yes"` and
  `check.drifted == []`; note render → `check.target_ok is True`; any `check.error` → failed;
  no `check_json` → not checked (not blocking).
- `finish` refuses at most 3 times per run; the 3rd refusal sets the run to `needs_input`.
- Migration: next free number after `0009` at execution time (put-into may take `0010`), name
  `<n>_board_agent`.

## Review Focus

1. **Agent calls a tool for an item on another board** (stale id from an earlier run) → refused
   `ITEM_NOT_ON_BOARD`, no change; test in Task 3.
2. **Two MCP sessions on one board** (person reconnects Claude Code) → both attach to the same open
   run; `set_goal` while a run is `running` replaces nothing and returns `RUN_ALREADY_OPEN` with the
   run id; test in Task 5.
3. **Item in the output is removed by the person mid-run** → `finish` refuses naming that item;
   test in Task 5.
4. **`wait` on a job that never finishes** → returns `{"state": "pending", "timed_out": true}`
   after `timeout_s` (max 120), never hangs the MCP request; test in Task 4.
5. **Browser opens a board mid-run** → the panel loads past steps from the REST endpoint, then
   live ones from SSE, with no duplicates (dedupe by step id); test in Task 8.

---

### Task 1: Agent run and step tables

**Files:**
- Create: `backend/alembic/versions/<n>_board_agent.py`
- Create: `backend/app/db/repos/agent.py`
- Modify: `backend/app/db/models.py` (add two classes), `backend/app/db/ids.py` (prefixes)
- Test: `backend/tests/unit/db/test_agent_repo.py`

**Interfaces:**
- Produces: models `AgentRun` (`agent_runs`: `id` `arun_…`, `board_id` FK, `source`
  `'mcp'|'muse'`, `status` `'running'|'needs_input'|'done'|'paused'`, `goal` str, `deliverables_json`
  list[str], `output_json` dict|None, `finish_refusals` int default 0, `note` str|None,
  `created_at`, `updated_at`) and `AgentStep` (`agent_steps`: `id` `astep_…`, `run_id` FK index,
  `board_id` index, `turn` int, `tool` str, `args_json`, `say` str|None, `ok` bool, `result_json`
  (summary, ≤ 4 KB), `item_ids_json` list[str], `highlight` bool default false, `created_at`).
  Named `AgentRun`, not `Run`, to stay clear of the Vary `VariationRun`/`runs` tables.
- Produces (repo): `open_run(session, board_id) -> AgentRun | None` (status `running` or
  `needs_input`), `create_run(session, board_id, source, goal, deliverables) -> AgentRun`,
  `add_step(session, run_id, **fields) -> AgentStep` (turn = previous max + 1),
  `steps(session, run_id) -> list[AgentStep]`, `runs(session, board_id) -> list[AgentRun]`
  (newest first), `run_to_dict(r)`, `step_to_dict(s)`.

- [ ] **Step 1: Write failing tests** `test_open_run_none_then_created`,
  `test_add_step_turns_increment` (three steps → turns `[1, 2, 3]`),
  `test_open_run_ignores_done` (a `done` run → `open_run` is `None`),
  `test_runs_newest_first`, using the `session` fixture.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/db/test_agent_repo.py -v` → FAIL (import error).
- [ ] **Step 3: Add the models, prefixes `"agent_run": "arun_", "agent_step": "astep_"`, the
  migration (create both tables, index `(board_id, created_at)` on steps) and the repo.**
- [ ] **Step 4: Run** the test file → PASS; `uv run pytest tests/integration/db -q` → PASS (migrations still run).
- [ ] **Step 5: Commit** `feat(agent): agent run and step tables`

---

### Task 2: Tool registry, in-process API client, step recording

**Files:**
- Create: `backend/app/agent/__init__.py`, `backend/app/agent/context.py`,
  `backend/app/agent/tools/__init__.py`, `backend/app/agent/steps.py`
- Test: `backend/tests/integration/agent/test_registry.py`, `backend/tests/integration/agent/conftest.py`

**Interfaces:**
- Consumes: Task 1 repo.
- Produces:
  - `class ApiClient` (`context.py`): wraps `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://muse.internal")`;
    `async get(path) / post(path, json=None, files=None) / patch(path, json) / delete(path) -> ApiResult`
    where `ApiResult = (status: int, body: Any)`. Paths are under `/api`. Import `app.main.app` lazily.
  - `@dataclass ToolContext(api: ApiClient, board_id: str | None, run_id: str | None, source: str)`.
  - Tool module contract: `DEFINITION: dict` (`name`, `description`, `parameters` JSON schema
    without `say`/`highlight` — the registry adds them) and `async def run(ctx, args) -> dict`.
    A tool may set `MCP_ONLY = True` and `NEEDS_BOARD = False` (default `True`).
  - `tools.definitions(source: str) -> list[dict]` (MCP_ONLY tools only for `source == "mcp"`).
  - `async tools.run_tool(ctx, name, args) -> dict`: unknown name → `UNKNOWN_TOOL`; `NEEDS_BOARD`
    and `ctx.board_id is None` → `NO_BOARD_OPEN`; strips `say`/`highlight`; runs the tool; catches
    any exception → `{"error": "TOOL_FAILED", "message": str(e)}` (logged); then, when a run is
    open, records a step (`steps.record(...)`) and publishes `agent.step` with `step_to_dict`.
    Result dict may carry `"item_ids": [...]` (stored on the step, used by the panel to focus).
  - `api_error(status, body) -> dict`: maps an `AppError` JSON body (`{"error": {"code", "message"}}`,
    check `app/errors.py` for the exact shape) to the tool error shape.

- [ ] **Step 1: Write failing tests** with a fake tool module registered in the test:
  `test_run_tool_records_step_and_publishes` (subscribe to the board, call, assert one
  `agent.step` event with `tool`, `say`, `ok: True`, and one row in `agent_steps`),
  `test_refusal_is_recorded_not_raised` (tool returns `{"error": ...}` → step `ok: False`),
  `test_exception_becomes_tool_failed`, `test_unknown_tool`, `test_no_board_open`,
  `test_no_step_without_open_run`, `test_say_trimmed_to_200`.
  `conftest.py` provides `ctx` (an `ApiClient` over the `client` fixture's app) and `board`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_registry.py -v` → FAIL.
- [ ] **Step 3: Implement** the four files.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(agent): tool registry over the in-process API, steps on the board feed`

---

### Task 3: Board, reference, note, item and lens tools

**Files:**
- Create in `backend/app/agent/tools/`: `create_board.py`, `list_boards.py`, `open_board.py`,
  `add_reference.py`, `upload_reference.py`, `add_note.py`, `visualize_note.py`, `move_item.py`,
  `remove_item.py`, `propose_lens.py`, `set_lens.py`, `read_board.py`
- Test: `backend/tests/integration/agent/test_board_tools.py`

**Interfaces:**
- Consumes: Task 2 contract.
- Produces (tool name → args → result):
  - `create_board(title, context?, domain?)` → `{"board_id"}`; sets `ctx.board_id`. `NEEDS_BOARD=False`.
  - `list_boards()` → `{"boards": [{id, title, domain, items}]}`. `NEEDS_BOARD=False`.
  - `open_board(board_id)` → board summary; sets `ctx.board_id`; sets `ctx.run_id` to
    `open_run(...)` if any. `NEEDS_BOARD=False`.
  - `add_reference(url, x?, y?)` → `{"item_id", "deduped"}` via `POST /boards/{id}/items` JSON.
  - `upload_reference(path, page_url?, x?, y?)` (`MCP_ONLY`) → reads a local image file
    (≤ the app's upload limit, image MIME only), posts multipart; when `page_url` is given, stores it
    on the item (`page_url`) through `PATCH /items/{id}` if the route allows it, otherwise add a
    `page_url` form field to the multipart ingest (small change in `api/items.py`, covered here).
  - `add_note(text, x?, y?)` → `{"item_id"}`; `visualize_note(note_id)` → `{"queued": true}`.
  - `move_item(item_id, x, y)`, `remove_item(item_id)`.
  - `propose_lens()`, `set_lens(lens_id)`.
  - `read_board()` → `{"board", "items": [{id, kind, role, x, y, w, h, note_text?, parse_status,
    analysis_status?, check?}], "profile": <GET /boards/{id}/profile>, "context": <GET /boards/{id}/context>}`,
    item list capped at 200, newest first.
  - Every tool taking an `item_id` first checks the item is on `ctx.board_id` →
    else `ITEM_NOT_ON_BOARD` (Review Focus 1).
  - Default placement when `x`/`y` are omitted: right of the board's current bounding box, 40 px gap,
    rows of 4 (helper `next_slot(items) -> (x, y)` in `context.py`).

- [ ] **Step 1: Write failing tests**: `test_create_then_open_board`, `test_add_reference_url`
  (a `*.test` URL served by `respx` as the existing ingest tests do; assert `item.added` event fires),
  `test_upload_reference_local_file` (writes a PNG to `tmp_path`, asserts `page_url` kept),
  `test_upload_reference_rejects_non_image`, `test_add_and_visualize_note`,
  `test_item_not_on_board` (item from board A while board B is open → `ITEM_NOT_ON_BOARD`),
  `test_read_board_shape`, `test_next_slot_rows_of_four`,
  `test_locked_demo_refuses_writes` (`DEMO_MODE=1`, no unlock → `add_note` returns the demo error).
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_board_tools.py -v` → FAIL.
- [ ] **Step 3: Implement** the tools (+ the `page_url` ingest field if needed).
- [ ] **Step 4: Run** → PASS; `uv run pytest tests/integration/api/test_items.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(agent): board, reference, note and lens tools`

---

### Task 4: Analysis, explore, plugin and wait tools

**Files:**
- Create in `backend/app/agent/tools/`: `analyse.py`, `get_analysis.py`, `add_dimension.py`,
  `explore.py`, `visualize_option.py`, `keep_option.py`, `unkeep_option.py`, `run_plugin.py`, `wait.py`
- Test: `backend/tests/integration/agent/test_explore_tools.py`

**Interfaces:**
- Produces:
  - `analyse(item_id)`, `get_analysis(item_id)` (dimensions with values, parts), `add_dimension(item_id, key, label, value?)`
    → the matching `api/analysis.py` routes. A daily-limit refusal comes back as its error code.
  - `explore(item_id, dimension)` → `{"exploration_id", "options": [{id, name, ...}]}`.
  - `visualize_option(option_id)` → `{"queued": true}`; `keep_option(option_id)`, `unkeep_option(option_id)`.
  - `run_plugin(plugin_id, node params...)`: thin over `POST /boards/{id}/nodes` + `POST /nodes/{id}/run`;
    args mirror the existing node body.
  - `wait(kind, id, timeout_s=60)` with `kind ∈ {"item", "analysis", "option", "note", "plugin_run"}`;
    polls the matching GET every 1 s until the state leaves pending/processing/visualizing;
    `timeout_s` clamped to `[1, 120]`; returns `{"state", "result", "timed_out": bool}`;
    for `option`/`note` the result includes the new item id and its `check` (Review Focus 4).
    Poll interval injectable (`POLL_S` module constant) so tests run fast.

- [ ] **Step 1: Write failing tests** (`JOBS_SYNC=1`, mock providers):
  `test_analyse_then_get_analysis`, `test_explore_returns_options`,
  `test_visualize_then_wait_returns_item_and_check`, `test_keep_option`,
  `test_wait_times_out` (patch the GET to stay `visualizing`, `timeout_s=1`, `POLL_S=0.05` →
  `timed_out: True`), `test_wait_clamps_timeout`, `test_run_plugin_colour`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_explore_tools.py -v` → FAIL.
- [ ] **Step 3: Implement.** Reuse request/response shapes from `tests/integration/api/test_explore.py`
  and `test_nodes_api.py` to learn the bodies.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(agent): analysis, explore, plugin and wait tools`

---

### Task 5: Goal, output sheet, and finish with the deliverables and consistency checks

**Files:**
- Create in `backend/app/agent/tools/`: `set_goal.py`, `compose_output.py`, `finish.py`
- Create: `backend/app/agent/checks.py`
- Modify: `backend/app/providers/reasoning.py` (mock: schema title `output_consistency`)
- Test: `backend/tests/integration/agent/test_goal_output.py`, `backend/tests/unit/agent/test_checks.py`

**Interfaces:**
- Produces:
  - `set_goal(goal, deliverables: list[str] (1–12, each ≤ 80 chars))` → creates an `AgentRun`
    (`source = ctx.source`), sets `ctx.run_id`, publishes `agent.run`. If a run is open →
    `{"error": "RUN_ALREADY_OPEN", "run_id"}` and `ctx.run_id` set to it (Review Focus 2).
    This step is recorded on the new run as turn 1.
  - `compose_output(title, sections: [{deliverable, items: [{item_id, why}]}])` → lays the sheet out
    right of the board's bounding box (80 px gap): a title note, then one row per section
    (section label note, then its items scaled to 320 px tall in order, each with a caption note
    `why` under it); moves items via `PATCH /items/{id}`; stores `{title, sections, note_ids}` in
    `run.output_json` (a second call replaces the sheet: old caption/title notes removed);
    publishes `agent.run`. Unknown deliverable name → `UNKNOWN_DELIVERABLE`.
  - `finish(summary)` → runs checks; pass → run `done`, `note = summary`, result `{"status": "done"}`;
    fail → `finish_refusals += 1`, result `{"error": "OUTPUT_NOT_READY", "problems": [...]}`; on the
    3rd refusal status `needs_input` and result `{"status": "needs_input", "problems": [...]}`.
  - `checks.check_passed(check: dict | None) -> bool | None` (rule in Global Constraints).
  - `checks.deliverable_problems(run, items_by_id) -> list[str]`: missing deliverables, items
    removed or not on the board (Review Focus 3), items whose check failed. Plain sentences naming
    the deliverable/item, e.g. `"'exterior side' has no item"`, `"itm_… was removed"`,
    `"itm_… failed its result check (drifted: roofline)"`.
  - `checks.consistency_problems(images: list[bytes], goal: str) -> list[str]`: one
    `get_reasoning(settings).structured(images[:12], CONSISTENCY_SCHEMA, prompt)` with schema
    `{"title": "output_consistency", "type": "object", "properties": {"one_design": {"type": "boolean"},
    "outliers": {"type": "array", "items": {"type": "integer"}}, "reason": {"type": "string"}}}`
    (outliers = 0-based image indexes); returns `[]` when `one_design` is true, else one problem per
    outlier mapped back to item ids plus the reason. Runs only after `deliverable_problems` is empty.
    A model failure is a problem `"consistency check unavailable: <code>"` (refuses, counts).
    The mock returns `{"one_design": true, "outliers": [], "reason": ""}`.

- [ ] **Step 1: Write failing unit tests** in `test_checks.py`: `check_passed` for explore yes/no/
  unclear/drifted, note `target_ok` true/false/None, `error`, `None` → `None`;
  `deliverable_problems` for missing, removed and failed items; `consistency_problems` with a
  monkeypatched provider returning outliers `[1]`.
- [ ] **Step 2: Write failing integration tests** in `test_goal_output.py`:
  `test_set_goal_opens_run_and_publishes`, `test_set_goal_twice_returns_open_run`,
  `test_compose_output_lays_out_and_stores`, `test_compose_output_replaces_previous_sheet`,
  `test_finish_done_when_all_delivered`, `test_finish_refuses_missing_deliverable`,
  `test_finish_refuses_removed_item` (person deletes an output item via `DELETE /api/items/{id}`),
  `test_third_refusal_needs_input`, `test_finish_refuses_inconsistent_output`.
- [ ] **Step 3: Run** both files → FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** → PASS.
- [ ] **Step 6: Commit** `feat(agent): goal, output sheet, finish with deliverables and consistency checks`

---

### Task 6: MCP server at /mcp

**Files:**
- Create: `backend/app/agent/mcp_server.py`
- Modify: `backend/pyproject.toml` (`uv add mcp`), `backend/app/config.py` (`MCP_ENABLED: bool = False`),
  `backend/app/main.py` (mount + lifespan), `.env.example` (`MCP_ENABLED=0` with a one-line comment)
- Test: `backend/tests/integration/agent/test_mcp.py`

**Interfaces:**
- Consumes: `tools.definitions("mcp")`, `tools.run_tool`.
- Produces: `build_mcp() -> <SDK server>` registering every definition as an MCP tool (schema from
  `DEFINITION["parameters"]` plus `say`/`highlight`); per MCP session one `ToolContext(source="mcp")`
  kept in a dict keyed by the SDK's session id (board and run survive across calls in a session).
  Tool results are returned as JSON text content. `mount_mcp(app)` mounts the SDK's
  streamable-HTTP ASGI app at `/mcp` and runs its session manager inside the FastAPI lifespan,
  only when `MCP_ENABLED`. Check the installed `mcp` 2.x API for the exact names
  (low-level `Server` with `list_tools`/`call_tool`, or `FastMCP`); prefer the low-level server since
  the tool schemas are already JSON schema. The SPA fallback must not swallow `/mcp`.

- [ ] **Step 1: Write failing tests** with the SDK's client (`streamablehttp_client` over the
  TestClient transport, or raw JSON-RPC POSTs with the required `Accept` headers):
  `test_mcp_disabled_404`, `test_mcp_lists_tools` (includes `create_board`, `upload_reference`,
  `finish`; every schema has `say`), `test_mcp_call_creates_board_and_note_in_one_session`
  (board opened by `create_board` is used by the next `add_note` in the same session),
  `test_mcp_sessions_are_separate`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_mcp.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; full backend `uv run pytest -q` → PASS; `uv run ruff check . && uv run mypy app` → clean.
- [ ] **Step 5: Commit** `feat(agent): MCP server at /mcp behind MCP_ENABLED`

---

### Task 7: Runs and steps read API, highlight toggle

**Files:**
- Create: `backend/app/api/agent.py`
- Modify: `backend/app/main.py` (include router), `backend/app/demo.py` (no new open writes: the
  highlight PATCH stays locked)
- Test: `backend/tests/integration/api/test_agent_api.py`

**Interfaces:**
- Produces:
  - `GET /api/boards/{board_id}/agent-runs` → `{"runs": [run_to_dict]}` newest first.
  - `GET /api/agent-runs/{run_id}` → run with `steps: [step_to_dict]` in turn order.
  - `PATCH /api/agent-steps/{step_id}` body `{"highlight": bool}` → step; publishes `agent.step`.
  - `run_to_dict` keys: `id, board_id, source, status, goal, deliverables, output, finish_refusals,
    note, created_at, updated_at`; `step_to_dict` keys: `id, run_id, turn, tool, args, say, ok,
    result, item_ids, highlight, created_at`.

- [ ] **Step 1: Write failing tests**: `test_list_runs_newest_first`, `test_run_with_steps_in_order`,
  `test_patch_highlight_publishes`, `test_patch_highlight_locked_in_demo`, `test_unknown_run_404`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(agent): read agent runs and steps, toggle highlights`

---

### Task 8: Agent panel on the board

**Files:**
- Modify: `frontend/src/api.ts` (types `AgentRun`, `AgentStep`; `getAgentRuns`, `getAgentRun`,
  `patchAgentStep`; `keys.agentRuns(boardId)`, `keys.agentRun(runId)`),
  `frontend/src/events.ts` (`'agent.step'`, `'agent.run'` in `EVENT_TYPES`; cache updates),
  `frontend/src/shell/AgentCard.tsx`, `frontend/src/shell/shell.css`
- Create: `frontend/src/shell/agentRun.ts` (pure helpers)
- Test: `frontend/src/shell/agentRun.test.ts`, `frontend/src/shell/AgentCard.test.tsx`, `frontend/src/events.test.ts`

**Interfaces:**
- Consumes: Task 7 endpoints and event payloads (`agent.step` data = `step_to_dict`,
  `agent.run` data = `run_to_dict` without steps).
- Produces:
  - `mergeSteps(prev: AgentStep[], incoming: AgentStep) -> AgentStep[]`: dedupe by `id` (replace
    in place, e.g. a highlight change), keep turn order (Review Focus 5).
  - `deliverableStatus(run: AgentRun) -> {name: string, done: boolean}[]` (done when the output
    has a section for it with ≥ 1 item).
  - `AgentCard` behaviour: with no run, unchanged (activity feed). With a latest run: header shows
    `Muse` or `Claude Code` (by `source`) and a status chip (`working`, `needs you`, `done`, `paused`);
    collapsed shows the latest step's `say` (falls back to the tool name); expanded shows the goal,
    the deliverables as a checklist, then steps newest first: `say` as a line, the tool call as a
    small monospace line (`tool(arg=value…)`, args truncated to 60 chars), refused steps marked.
    Clicking a step with `item_ids` calls the existing `onFocusItem` for the first item
    (pass it down from `BoardShell`). A star button on each step toggles `highlight` (hidden when
    the board is locked). The input stays disabled; placeholder becomes `"Claude Code is working"`
    while an MCP run is `running`, else unchanged.

- [ ] **Step 1: Write failing tests**: `agentRun.test.ts` (`mergeSteps` dedupe and order,
  `deliverableStatus`); `events.test.ts` (an `agent.step` event updates `keys.agentRun` cache; an
  `agent.run` event updates `keys.agentRuns`); `AgentCard.test.tsx` (`shows the latest say
  collapsed`, `lists goal, deliverables and steps expanded`, `clicking a step focuses its item`,
  `refused step is marked`, `star hidden when locked`, `placeholder says Claude Code is working`).
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/shell src/events.test.ts` → FAIL.
- [ ] **Step 3: Implement**, matching the card's existing markup and CSS idiom.
- [ ] **Step 4: Run** → PASS; `npx tsc --noEmit && npm run lint && npx vitest run` → PASS.
- [ ] **Step 5: Commit** `feat(agent): live agent panel in the board's agent card`

---

### Task 9: Connect Claude Code, and an end-to-end check against the real app

**Files:**
- Modify: `README.md` (section "Working a board from Claude Code (MCP)")
- Create: `backend/tests/integration/agent/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing test** `test_goal_to_done_over_mcp`: one MCP session runs
  `create_board` → `set_goal("A test chair", ["front view", "colour option"])` → `add_note` ×2 →
  `visualize_note` ×2 → `wait` ×2 → `compose_output` → `finish` and asserts the run is `done`,
  every call left a step, and the board SSE saw `agent.run`, `agent.step` and `item.added`.
- [ ] **Step 2: Run** → FAIL until wiring gaps are fixed; fix them; run → PASS.
- [ ] **Step 3: Write the README section**: set `MCP_ENABLED=1`, `make dev`, then
  `claude mcp add --transport http muse http://localhost:8000/mcp`; a sample first prompt
  ("Create a board called EV coupe, set a goal with these deliverables…, narrate each step with
  `say`"); what the person sees (items landing, the agent card's steps). Note that Muse Code uses the
  same URL.
- [ ] **Step 4: Manual check against the running app** (mock providers are fine): start
  `make dev` with `MCP_ENABLED=1`, connect Claude Code, open the board in the browser, run the sample
  prompt, confirm the agent card fills step by step and items land live. Record what was seen in the
  task report.
- [ ] **Step 5: Commit** `docs(agent): connect Claude Code over MCP; end-to-end test`
