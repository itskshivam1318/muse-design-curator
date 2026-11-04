# Board Chat Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent card's chat box drives the board in plain language: a Muse Spark tool loop on the backend, a chat thread with questions and part confirmation on the frontend.

**Architecture:** A message route stores the person's message and starts (or feeds) an async loop for the board's open chat run. The loop calls Muse Spark (Responses API, function tools) and runs the existing tool registry through `ToolContext`, so every action goes through the REST API. `ask_user` / `confirm_part` pause the run (`needs_input`); the person's answer resumes it. Messages, steps and questions reach the card as board events.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (SQLite), openai SDK against Meta's Model API (`muse-spark-1.3`), pytest; React + TanStack Query + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-04-board-chat-agent-design.md` (read it; this plan argues from it).

## Global Constraints

- Muse Spark only for the loop; Muse Image only for pictures. Client: `app.providers.meta_client.get_client(settings)`, model `settings.MUSE_SPARK_MODEL`.
- Chat is available only when `REASONING_PROVIDER == "muse-spark"` and `DEMO_MODE` is off; otherwise the route refuses (`CHAT_UNAVAILABLE`) and the input says why.
- Chat runs use the existing source value **`"muse"`** (already in `AGENT_SOURCES`; the spec's `"chat"` maps to it). MCP runs stay `"mcp"`.
- Tools act only through the REST API (`ToolContext.api`); never write board tables from the loop.
- `backend/app/` must not contain the words watch, fashion, interior, dial, sofa (enforced by a test).
- Migration number **0012**, `down_revision = "0011_board_agent"`.
- At most **40** model steps per person message (`MAX_STEPS = 40`).
- `say` is at most 200 characters (existing `SAY_MAX`).
- Backend checks: `cd backend && uv run pytest -q`, `uv run ruff check .`, `uv run mypy app scripts`. Frontend: `cd frontend && npm test`, `npm run lint`, `npx tsc -b`.
- Work in the worktree `../muse-agent-chat` on `feat/board-chat-agent`. Never touch `../muse-design-curator` (main's tree) or its dev DB.

## Review Focus

1. **A message sent while the loop is working** is queued and picked up at the next step, never lost and never starts a second loop → test in Task 7 (`test_message_during_turn_is_picked_up`) and Task 8 (`test_second_message_does_not_start_second_loop`).
2. **Muse Spark errors or timeouts mid-turn** leave the run open (`waiting`) with an agent message naming the error, not stuck in `running` → Task 7 `test_model_error_posts_message_and_waits`.
3. **The backend restarts while a run is `running`** → on startup, open `muse` runs in `running` go to `waiting` so the card does not show working forever → Task 8 `test_startup_resets_running_chat_runs`.
4. **An answer arrives for a question that is no longer open** (double click, stale tab) → 409 `NO_OPEN_QUESTION`, no loop started → Task 8 `test_stale_answer_rejected`.
5. **Tool results with huge payloads** (`read_board` with 200 items, `get_analysis`) do not blow up the next call → compaction caps each kept output at 6000 chars → Task 6 `test_long_tool_output_capped`.

---

## File Structure

Backend (`backend/app/agent/chat/` is new):
- `alembic/versions/0012_board_chat.py` — `agent_messages` table, `agent_runs.history_json`, status `waiting`.
- `app/db/models.py` — `AgentMessage`, `AgentRun.history_json`, `AGENT_STATUS` + `waiting`.
- `app/db/repos/agent.py` — message functions; source-aware `open_run`.
- `app/agent/run_state.py` — `OPEN` + `waiting`; source-aware `start`/`current`.
- `app/agent/tools/set_goal.py` — refuse over an open chat run.
- `app/agent/tools/{add_part,remove_part,extract_part,wait_all,update_goal}.py` — new registry tools.
- `app/put/service.py`, `app/views/service.py` — result checks.
- `app/agent/chat/model.py` — `ChatModel` protocol, `MuseSparkChat`, `ModelTurn`, `get_chat_model`.
- `app/agent/chat/history.py` — compaction.
- `app/agent/chat/trace.py` — JSONL traces.
- `app/agent/chat/prompt.py` — system instructions.
- `app/agent/chat/local_tools.py` — `ask_user`, `confirm_part`, `look_at` definitions + handlers.
- `app/agent/chat/loop.py` — `run_turn`.
- `app/agent/chat/runner.py` — one task per board, queueing, stop flag, startup reset.
- `app/api/agent.py` — chat routes.
- `app/config.py` — `AGENT_TRACES`.

Frontend:
- `src/api.ts` — types + calls.
- `src/events.ts` — `agent.message`, `agent.question` cache updates.
- `src/shell/chat/ChatThread.tsx`, `ChatInput.tsx`, `QuestionCard.tsx` (+ tests).
- `src/shell/AgentCard.tsx` — mount the chat.
- `src/canvas/PartConfirmLayer.tsx` (+ test) — mask highlight and Fix box.
- `src/put/ConnectLayer.tsx` / `PutCard.tsx` — card placement.

---

### Task 1: Schema — messages, history, `waiting`

**Files:**
- Create: `backend/alembic/versions/0012_board_chat.py`
- Modify: `backend/app/db/models.py:531-552`, `backend/app/db/repos/agent.py`, `backend/app/agent/run_state.py:14`
- Test: `backend/tests/integration/agent/test_chat_repo.py`

**Interfaces:**
- Produces:
  - `AGENT_STATUS = ("running", "needs_input", "waiting", "done", "paused")`
  - `AgentRun.history_json: Mapped[Any]` (nullable JSON list of Responses input items)
  - `AgentMessage` table `agent_messages`: `id` (prefix `agent_msg`), `run_id` FK, `board_id`, `role` in `("person", "agent", "question")`, `text: str`, `data_json` (JSON, nullable), `answered: bool` (default False; questions only), `created_at`.
  - `agent_repo.add_message(session, run_id: str, board_id: str, role: str, text: str, data: dict | None = None) -> AgentMessage`
  - `agent_repo.messages(session, run_id: str) -> list[AgentMessage]` (oldest first)
  - `agent_repo.open_question(session, run_id: str) -> AgentMessage | None` (latest unanswered `question`)
  - `agent_repo.message_to_dict(m) -> dict` keys `id, run_id, role, text, data, answered, created_at`
  - `agent_repo.open_run(session, board_id, source: str | None = None)` — statuses `run_state.OPEN`; filtered by source when given.
  - `run_state.OPEN = ("running", "needs_input", "waiting")`

- [ ] **Step 1: Write failing tests** in `test_chat_repo.py`: `test_message_round_trip` (add person + question, `messages()` returns both in order, `message_to_dict` keys exact); `test_open_question_latest_unanswered`; `test_open_run_includes_waiting`; `test_open_run_filters_by_source` (a `muse` run open, `open_run(s, b, "mcp")` is None).
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_chat_repo.py -q` → FAIL (no `add_message`).
- [ ] **Step 3: Migration** with `op.batch_alter_table("agent_runs", recreate="always")`: add `history_json` JSON; drop and recreate `ck_agent_run_status` with the new list. Create `agent_messages` with index on `run_id` and a check on `role`. Downgrade reverses (map `waiting` rows to `paused` first).
- [ ] **Step 4: Model + repo + `OPEN`** as in Interfaces. `run_to_dict` unchanged (history is not sent to the UI).
- [ ] **Step 5: Run** the new tests and `uv run pytest tests/integration/agent -q` → PASS; `uv run alembic upgrade head` on a temp DB (`DATABASE_URL=sqlite:////tmp/x.sqlite`) → no error.
- [ ] **Step 6: Commit** `feat(agent): chat messages, run history, waiting status (0012)`.

### Task 2: MCP and chat runs on one board

**Files:**
- Modify: `backend/app/agent/run_state.py`, `backend/app/agent/tools/set_goal.py`, `backend/app/agent/mcp_server.py` (only if it calls `current` without a source)
- Test: `backend/tests/integration/agent/test_goal_output.py` (add)

**Interfaces:**
- Consumes: Task 1 `open_run(..., source)`.
- Produces: `run_state.start(board_id, source, goal, deliverables, replace=False)` — looks only at runs of `source` when joining; when another source's run is open: `source == "mcp"` and the open run is `muse` → returns `({"error": "CHAT_OPEN", ...}, False)` unless `replace`, which sets the chat run to `done` and starts the MCP run. `run_state.current(board_id, run_id, source: str | None = None)` falls back only to an open run of `source`.

- [ ] **Step 1: Failing tests:** `test_set_goal_refused_while_chat_open` (create a `muse` run via `run_state.start(b, "muse", "g", [])`; MCP `set_goal` → `error == "CHAT_OPEN"`); `test_set_goal_replace_ends_chat_run` (chat run status `done`, new run `mcp`); `test_current_does_not_fall_back_across_sources`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** per Interfaces; `set_goal` passes `ctx.source` and turns the error tuple into its refusal. Allow `deliverables == []` for `source == "muse"` in `run_state.start` (MCP `set_goal` keeps `minItems: 1` in its schema).
- [ ] **Step 4: Run** `uv run pytest tests/integration/agent -q` → PASS.
- [ ] **Step 5: Commit** `feat(agent): MCP refuses to join an open chat run`.

### Task 3: Registry tools — parts, wait_all, update_goal

**Files:**
- Create: `backend/app/agent/tools/add_part.py`, `remove_part.py`, `extract_part.py`, `wait_all.py`, `update_goal.py`
- Modify: `backend/app/agent/tools/__init__.py` (`_MODULES`)
- Test: `backend/tests/integration/agent/test_part_tools.py`

**Interfaces:**
- `add_part(item_id, label, box?: [x0,y0,x1,y1] fractions)` → `POST /api/items/{id}/parts` with `{"label", "region": {"kind": "mask", "box"}}` when box given; then `GET /api/items/{id}/parts/{key}/region`. Result `{"part": {...}, "region": {...}, "item_ids": [item_id]}`. On region 422 `REGION_EMPTY`: `DELETE` the part and return `{"error": "REGION_EMPTY", "message": "Nothing found for this part; try a shorter name or draw a box."}`.
- `remove_part(item_id, part)` → `DELETE /api/items/{id}/parts/{part}`; `{"removed": part, "item_ids": [item_id]}`.
- `extract_part(item_id, part)` → `POST /api/items/{id}/parts/{part}/extract`; `{"item_id": new_id, "item_ids": [new_id]}`.
- `wait_all(kind, ids: list[str] (1..6), timeout_s=120)` → runs `wait`'s probe for each concurrently (`asyncio.gather` over `wait.run`), result `{"results": {id: wait_result}, "item_ids": [...all focus ids]}`.
- `update_goal(goal?, deliverables?)` → `run_state.update(ctx.run_id, goal=..., deliverables_json=...)`; `NO_RUN` refusal without a run.

- [ ] **Step 1: Failing tests** (use the `ctx` fixture; segmentation is mocked in tests — follow `tests/integration/test_locate.py` for how regions are faked): `test_add_part_returns_region`, `test_add_part_with_box_stores_hint` (part `region` equals the box), `test_add_part_empty_region_removes_part` (afterwards `get_analysis` has no such part), `test_remove_part`, `test_extract_part_creates_item`, `test_wait_all_returns_each`, `test_update_goal_sets_deliverables`, and registry: `"add_part" in [d["name"] for d in tools.definitions("muse")]`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_part_tools.py -q` → FAIL.
- [ ] **Step 3: Implement** each module with `DEFINITION` + `run` per the registry docstring.
- [ ] **Step 4: Run** → PASS; the banned-words test still passes.
- [ ] **Step 5: Commit** `feat(agent): add_part, remove_part, extract_part, wait_all, update_goal tools`.

### Task 4: Put-into and view results get a check

**Files:**
- Modify: `backend/app/put/service.py`, `backend/app/views/service.py`, `backend/app/agent/checks.py` (only if `check_passed` needs `unclear` handling)
- Test: `backend/tests/integration/test_put_into.py`, `test_views.py` (add to the existing files for these services)

**Interfaces:**
- Consumes: `app.explore.check.check_target_only(image: bytes, note_text: str) -> dict`.
- Produces: the new item's check stored the same way a visualised note's check is stored, so `read_board`/`wait` show `check.target`. Target text: put-into = `words` if given, else `f"{source_name} placed at the marked spot"`; render-view = `f"the same design seen from {view}"`. `deliverable_problems` blocks on `answer == "no"`, not on `"unclear"`.

- [ ] **Step 1: Failing tests:** `test_put_result_has_check`, `test_view_result_has_check` (mock reasoning `check_target` → `{"answer": "no", ...}`; the item's check `target.answer == "no"`); `test_unclear_check_does_not_block_finish` in `tests/unit/agent/test_checks.py`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: call the check after the job ingests the new item, inside the job, catching model errors (a failed check call leaves `check` null, logged).
- [ ] **Step 4: Run** the touched test files → PASS.
- [ ] **Step 5: Commit** `feat(put,views): results carry a target check`.

### Task 5: The chat model client

**Files:**
- Create: `backend/app/agent/chat/__init__.py`, `backend/app/agent/chat/model.py`
- Test: `backend/tests/unit/agent/test_chat_model.py`

**Interfaces:**
- Produces:
  - `@dataclass ToolCall: name: str; arguments: dict[str, Any]; call_id: str`
  - `@dataclass ModelTurn: output: list[dict[str, Any]]; text: str; calls: list[ToolCall]; usage: dict[str, Any]; latency_s: float`
  - `class ChatModel(Protocol): def respond(self, instructions: str, input: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn`
  - `class MuseSparkChat(ChatModel)` — `client.responses.create(model=..., instructions=..., input=..., tools=[{"type": "function", **t} for t in tools], reasoning={"effort": "medium"}, store=False)`; `output = [o.model_dump(exclude_none=True) for o in resp.output]`; unparseable `arguments` → `{}` plus `_bad_arguments: True` in the call's arguments so the loop can refuse it.
  - `class FakeChatModel(ChatModel)` — constructed with a list of scripted `ModelTurn`s; records every `(instructions, input, tools)` it got in `.calls`.
  - `get_chat_model(settings) -> ChatModel | None` — `None` unless `REASONING_PROVIDER == "muse-spark"` and `MODEL_API_KEY` set.
  - `ModelError` from `app.providers.reliability` is what `respond` raises on API failure (wrap via `call_model`).

- [ ] **Step 1: Failing tests:** `test_get_chat_model_none_for_mock` (`REASONING_PROVIDER="mock"`); `test_muse_spark_chat_parses_calls` (stub client whose `responses.create` returns an object with `output=[reasoning, message, function_call]`, `usage`) → one `ToolCall`, `text` from the message; `test_bad_arguments_flagged`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(agent): Muse Spark chat model client`.

### Task 6: History compaction and traces

**Files:**
- Create: `backend/app/agent/chat/history.py`, `backend/app/agent/chat/trace.py`
- Modify: `backend/app/config.py` (`AGENT_TRACES: bool = True`)
- Test: `backend/tests/unit/agent/test_chat_history.py`, `test_chat_trace.py`

**Interfaces:**
- `compact(items: list[dict], keep_turns: int = 2) -> list[dict]` — a "turn" starts at each `{"role": "user", ...}` item that carries `"muse_person": True` (the loop marks person messages so tool-image messages don't count). Before the last `keep_turns` turns: `function_call_output.output` → `json.dumps({"summary": output[:200]})`; `input_image` parts removed; `reasoning` items removed. Within kept turns: each `function_call_output.output` capped at 6000 chars. Never drops a `function_call` without its output (the API rejects orphans).
- `Trace(run_id: str, data_dir: Path)` with `.model_call(turn, step, request_items_count, new_items, turn_result: ModelTurn)`, `.tool(name, args, result, latency_s)`, `.message(role, text)`; appends JSON lines to `{DATA_DIR}/agent_traces/{run_id}.jsonl`; data URLs replaced by `<image N chars>`, `encrypted_content` by `<encrypted N chars>`. No-op when `AGENT_TRACES` is false.
- `trace_path(run_id) -> Path`.

- [ ] **Step 1: Failing tests:** `test_old_tool_outputs_summarised`, `test_old_images_dropped`, `test_kept_turns_untouched`, `test_long_tool_output_capped` (a 20000-char output in a kept turn → 6000), `test_call_output_pairs_preserved`; `test_trace_scrubs_images_and_reasoning`, `test_trace_off_writes_nothing`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(agent): chat history compaction and JSONL traces`.

### Task 7: The loop

**Files:**
- Create: `backend/app/agent/chat/prompt.py`, `local_tools.py`, `loop.py`
- Test: `backend/tests/integration/agent/test_chat_loop.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5, 6; `tools.definitions("muse")`, `tools.run_tool`.
- Produces:
  - `prompt.SYSTEM: str` — the spec §5.5 rules 1–9, plus "The board is open; its id is given in the first message".
  - `CHAT_HIDDEN = {"create_board", "list_boards", "open_board", "upload_reference", "set_goal", "finish"}`
  - `local_tools.DEFINITIONS` for `ask_user(question, choices?: list[str])` (choices may be item ids), `confirm_part(item_id, part, why)`, `look_at(item_ids ≤ 6)`.
  - `async def run_turn(board_id: str, run_id: str, model: ChatModel, api: ApiClient | None = None, should_stop: Callable[[], bool] = lambda: False, next_message: Callable[[], dict | None] = lambda: None) -> str` — returns the run's status after the turn (`"waiting"` or `"needs_input"`).
- Behaviour (algorithm the tests pin):
  1. Load `history_json` (or `[]`); append the run's unconsumed person messages (with `selection` → `"Selected on the board: itm_…, itm_…"`), marked `muse_person`. First turn prefixes `"[Board {board_id} is open.]"`.
  2. Up to `MAX_STEPS`: `should_stop()` → break; `model.respond(SYSTEM, compact(history), tools)`; trace; extend history with `turn.output`.
  3. No calls → post an `agent` message with `turn.text` (event `agent.message`), status `waiting`, save, return.
  4. For each call: `ask_user`/`confirm_part` → post a `question` message with `data = {"call_id", "tool", "args", "region"?}` (for `confirm_part`, fetch `GET /api/items/{id}/parts/{part}/region` into `region`), publish `agent.question`, status `needs_input`, save history, return. `look_at` → output `{"ok": true}` and append a `muse_person`-less user item with the images (`data_url` of `GET /api/items/{id}/image`). Hidden or unknown tool → `{"error": "NOT_AVAILABLE"}`. Bad arguments → `{"error": "BAD_ARGUMENTS"}`. Else `tools.run_tool(ctx, name, args)` with `ctx = ToolContext(api, board_id, run_id, source="muse")`.
  5. After the calls, `next_message()` → if a person message arrived, append it.
  6. Step cap → agent message "I stopped after 40 steps. Tell me how to continue." and `waiting`.
  7. `ModelError` → agent message `f"Muse Spark failed ({code}). Send a message to try again."`, status `waiting`, return.
  - Resuming after a question: the answering message's `data.answer` becomes that call's `function_call_output` (`{"answer": text}` or `{"box": [...]}` or `{"choice": id}`), and the question is marked `answered`.

- [ ] **Step 1: Failing tests** with `FakeChatModel` scripted from the spike runs:
  - `test_reply_without_tools_posts_agent_message` (status `waiting`, one agent message).
  - `test_tool_call_runs_registry_and_records_step` (`read_board` → an `agent_step` with the `say`).
  - `test_ask_user_suspends_and_answer_resumes` (status `needs_input`; feed an answer; the next model input contains `function_call_output` with the answer; final `waiting`).
  - `test_confirm_part_question_carries_region`.
  - `test_box_answer_reaches_model` (answer `{"box": [0.1,0.2,0.3,0.4]}` appears in the call output).
  - `test_hidden_tool_refused` (`finish` → `NOT_AVAILABLE`, no step recorded).
  - `test_selection_in_person_message` (the first model input text contains the selected ids).
  - `test_stop_flag_halts_before_next_call`.
  - `test_step_cap_message` (a model that always calls `read_board`; 40 calls then the stop message).
  - `test_model_error_posts_message_and_waits`.
  - `test_message_during_turn_is_picked_up`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/agent/test_chat_loop.py -q` → FAIL.
- [ ] **Step 3: Implement** `prompt.py`, `local_tools.py`, `loop.py`. Run state writes via `run_state.update`; messages via a small `run_in_threadpool` helper around `agent_repo.add_message` + `events.publish(board_id, "agent.message", message_to_dict(m))`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(agent): the board chat loop`.

### Task 8: Runner and routes

**Files:**
- Create: `backend/app/agent/chat/runner.py`
- Modify: `backend/app/api/agent.py`, `backend/app/main.py` (startup hook)
- Test: `backend/tests/integration/agent/test_chat_routes.py`

**Interfaces:**
- Consumes: Task 7 `run_turn`, Task 5 `get_chat_model`, Task 6 `trace_path`.
- Produces:
  - `runner.kick(board_id: str, run_id: str) -> None` — if no task is running for the board, `asyncio.create_task` one that loops `run_turn` while unconsumed person messages remain; with `settings.JOBS_SYNC`, awaits inline instead (`async def kick_sync`). One task per board (dict keyed by board id).
  - `runner.stop(run_id) -> None` (sets the flag `run_turn` polls); `runner.reset_running_on_startup() -> int`.
  - Routes:
    - `POST /api/boards/{board_id}/agent/messages` body `{text: str (1..2000), selection: list[str] = [], answer: {call_id: str, text?: str, choice?: str, box?: list[float]} | None}` → 202 `{run: run_to_dict, message: message_to_dict}`. Refusals: `CHAT_UNAVAILABLE` 409 (demo mode or no chat model, message says which), `MCP_RUN_OPEN` 409, `NO_OPEN_QUESTION` 409 (an `answer` whose `call_id` matches no open question). Plain text sent while a question is open is taken as the answer `{call_id: <open question>, text}` (document this in the route docstring).
    - `GET /api/agent-runs/{run_id}/messages` → `{messages: [...]}`.
    - `POST /api/agent-runs/{run_id}/new-chat` → run `done`, 200 run dict.
    - `PATCH /api/agent-runs/{run_id}` `{status: "paused"}` on a `muse` run → `runner.stop`, status `waiting` (MCP runs unchanged).
    - `GET /api/agent-runs/{run_id}/trace` → the JSONL as `text/plain`, 404 when `AGENT_TRACES` is off or no file.
    - `GET /api/agent/chat-status` → `{available: bool, reason: str | null}` for the input.

- [ ] **Step 1: Failing tests** (monkeypatch `get_chat_model` to a `FakeChatModel`; `JOBS_SYNC` is on in tests): `test_first_message_opens_muse_run`, `test_second_message_joins_run`, `test_second_message_does_not_start_second_loop`, `test_answer_resumes_question`, `test_stale_answer_rejected`, `test_text_while_question_open_is_answer`, `test_stop_sets_waiting`, `test_new_chat_done_then_new_run`, `test_refused_in_demo_mode`, `test_refused_without_chat_model`, `test_refused_while_mcp_run_open`, `test_trace_route`, `test_startup_resets_running_chat_runs`, `test_messages_route_order`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** runner and routes; call `reset_running_on_startup()` from the app's existing startup/lifespan.
- [ ] **Step 4: Run** `uv run pytest -q` (whole backend), `uv run ruff check .`, `uv run mypy app scripts` → PASS/clean.
- [ ] **Step 5: Commit** `feat(agent): chat routes and runner`.

### Task 9: Frontend data — types, calls, events

**Files:**
- Modify: `frontend/src/api.ts:256-300,516-517,651-658`, `frontend/src/events.ts:42-43,370-395`
- Test: `frontend/src/events.test.ts`, `frontend/src/api.test.ts` (if present; else in `events.test.ts`)

**Interfaces:**
- `AgentRunStatus` adds `'waiting'`.
- `interface AgentMessage { id: string; run_id: string; role: 'person' | 'agent' | 'question'; text: string; data: AgentMessageData | null; answered: boolean; created_at: string }`
- `interface AgentMessageData { selection?: string[]; call_id?: string; tool?: 'ask_user' | 'confirm_part'; args?: Record<string, unknown>; region?: { kind: string; box: number[] | null; mask_url: string | null } | null; answer?: AgentAnswer }`
- `interface AgentAnswer { call_id: string; text?: string; choice?: string; box?: number[] }`
- `keys.agentMessages(runId)`; `getAgentMessages(runId)`, `sendAgentMessage(boardId, { text, selection, answer? })`, `newChat(runId)`, `getChatStatus()`.
- Events: `agent.message` and `agent.question` append into `keys.agentMessages(run_id)` (dedupe by id); `agent.run` already updates runs.

- [ ] **Step 1: Failing tests:** `agent.message appends to the run's messages once` (same event twice → one entry); `agent.question appends`.
- [ ] **Step 2: Run** `npm test -- events` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`, `npx tsc -b` → PASS.
- [ ] **Step 5: Commit** `feat(frontend): chat agent types, calls and events`.

### Task 10: The chat in the agent card

**Files:**
- Create: `frontend/src/shell/chat/ChatThread.tsx`, `ChatInput.tsx`, `chatThread.ts` (pure merge), tests beside them
- Modify: `frontend/src/shell/AgentCard.tsx`, `frontend/src/shell/shell.css`

**Interfaces:**
- Consumes: Task 9; `useSelection()` (selected ids), `useDemo()`, existing `useRun`, `toolCall`.
- Produces:
  - `threadEntries(messages: AgentMessage[], steps: AgentStep[]): Entry[]` — merged by `created_at`; `Entry = { kind: 'message', message } | { kind: 'step', step }`.
  - `<ChatThread entries onFocusItem />` — person/agent bubbles; steps as the existing compact `say` line; `itm_…` ids in agent text rendered as buttons calling `onFocusItem`.
  - `<ChatInput boardId run disabledReason selectionCount onSend />` — Enter sends; a chip "About: N picture(s) selected" when N > 0; disabled with `disabledReason` as placeholder.
- Disabled reasons (exact copy): demo → `"Chat is off in the demo. Use “Show me how” to watch a run."`; MCP run open → `"Claude Code is working"`; no chat model → `"Chat needs Muse Spark (REASONING_PROVIDER=muse-spark)"`.
- Card: **Stop** while `running`; **New chat** when a `muse` run is open and not `running`; the thread replaces the step list for `muse` runs (MCP runs keep today's view); "Show me how" unchanged for `done` runs.

- [ ] **Step 1: Failing tests:** `threadEntries orders by time`; `ChatInput sends text with selection` (mock `sendAgentMessage`, selection `['itm_1']` → called with `{text, selection: ['itm_1']}`); `ChatInput shows demo reason`; `AgentCard shows New chat for a waiting muse run`; `agent text item ids are clickable` (click → `onFocusItem('itm_1')`).
- [ ] **Step 2: Run** `npm test -- chat AgentCard` → FAIL.
- [ ] **Step 3: Implement.** Keep `AgentCard.tsx` as the container; the new pieces live in `shell/chat/`.
- [ ] **Step 4: Run** `npm test`, `npm run lint`, `npx tsc -b` → PASS.
- [ ] **Step 5: Commit** `feat(frontend): chat thread in the agent card`.

### Task 11: Questions and part confirmation

**Files:**
- Create: `frontend/src/shell/chat/QuestionCard.tsx`, `frontend/src/canvas/PartConfirmLayer.tsx`, tests beside them
- Modify: `frontend/src/shell/chat/ChatThread.tsx`, `frontend/src/canvas/Canvas.tsx` (mount the layer), `frontend/src/shell/shell.css`

**Interfaces:**
- Consumes: Task 9 `AgentMessage` with `role === 'question'`; existing canvas framing used by spotlight (`frameItem`-style helper in `Canvas.tsx` from ae00f83 — reuse it).
- Produces:
  - `<QuestionCard message onAnswer(answer: AgentAnswer) />` — `ask_user`: one button per choice (item-id choices render the item thumbnail from `/api/items/{id}/image`), plus a text field. `confirm_part`: **Yes** (`{call_id, text: "yes"}`), **Fix** (enters box mode), text field.
  - A small store `partConfirm` (`{ itemId, maskUrl, box, mode: 'show' | 'draw' } | null`) set by `QuestionCard`, read by `PartConfirmLayer`.
  - `<PartConfirmLayer />` — frames the item, draws the mask tinted (pink at 55% opacity) and the box outline; in `draw` mode a drag on the item yields `box` as fractions of the item; release sends `{call_id, box}`; Esc returns to `show`.

- [ ] **Step 1: Failing tests:** `ask_user choices render as buttons and answer with choice`; `item-id choices render thumbnails`; `confirm_part Yes answers yes`; `Fix then drag sends box fractions` (simulate pointer down/move/up over a 200×100 item from (20,10) to (120,60) → `box [0.1, 0.1, 0.6, 0.6]`); `Esc leaves draw mode`; answered questions render without buttons.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`, `npm run lint`, `npx tsc -b` → PASS.
- [ ] **Step 5: Commit** `feat(frontend): agent questions and part confirmation on the board`.

### Task 12: Put card avoids the agent card

**Files:**
- Modify: `frontend/src/put/ConnectLayer.tsx` (`CardOnLine` placement), `frontend/src/put/PutCard.tsx` if placement lives there
- Test: `frontend/src/put/ConnectLayer.test.tsx`

**Interfaces:**
- `placeCard(drop: {x, y}, card: {w, h}, viewport: {w, h}, avoid: DOMRect[]): {x, y}` — pure; tries right-below, left-below, right-above, left-above of the drop point; first that fits the viewport (16 px margin) and overlaps no `avoid` rect; else clamps into the viewport. `avoid` = the agent card's rect (`.agent-card` element).

- [ ] **Step 1: Failing tests:** `placeCard keeps the card inside the viewport`; `placeCard avoids the agent card` (drop at bottom-right under a 340×160 agent rect → card placed left/above, no overlap).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** and use it in `CardOnLine`.
- [ ] **Step 4: Run** `npm test` → PASS.
- [ ] **Step 5: Commit** `fix(put): the Put card stays clear of the agent card and the screen edge`.

### Task 13: End-to-end with the real model

**Files:** none committed except a short note in `docs/demo/boards.md` if useful.

- [ ] **Step 1:** In the worktree, run the backend on a **separate port and DB copy** (`DATABASE_URL=sqlite:///./data/chat-e2e.sqlite`, port 8010) and the frontend against it, `REASONING_PROVIDER=muse-spark`.
- [ ] **Step 2:** On a car board with 4 references, send the three spike requests from the card (body → retro-futuristic with the E-Type selected; wheel caps on the Lancia with a Fix box; grille onto the red car). Expected: no wrong-item pick, the drawn box changes the mask, the put-into result shows a check.
- [ ] **Step 3:** Download each trace from the card; confirm per-call input tokens stay under 30k after the second turn.
- [ ] **Step 4:** Record findings in the PR description; fix anything blocking before merge.
