# Round 2: calm board, text-first axis, notes, plugin nodes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the board screen with the calm Round 2 shell, turn explore options into a text-first axis with staged takes and Keep, add notes with Visualize, and add a plugin engine whose nodes run on board items.

**Architecture:** Backend (FastAPI + SQLAlchemy + Alembic, `backend/app`) gains one migration (`0007_round2`), a notes module, staged-take keep endpoints, and a `plugins` package (manifest, discovery, runners, nodes, runs as `jobs` + board SSE events). Frontend (React 19 + react-konva, `frontend/src`) gains a `shell/` layout, note and axis canvas nodes, and a `plugins/` area (panel, node cards). Existing panels are re-homed, not rewritten.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pytest; React 19, react-konva, @tanstack/react-query, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-round2-calm-board-plugins-design.md` (read it before every task; the artboards it names are the visual reference — copies are in `docs/superpowers/specs/round2-artboards/`).

## Global Constraints

- Worktree `/Users/shivam/Desktop/muse-round2`, branch `feat/round2-calm-board-plugins`, base `main` at `12fbb91`. Never touch `/Users/shivam/Desktop/muse-design-curator` or `/Users/shivam/Desktop/muse-explore`.
- Baseline must stay green: 690 backend (`cd backend && uv run pytest -q`), 177 frontend (`cd frontend && npm test`), lint (`make lint`: ruff + mypy, oxlint + `tsc -b`, extension lint), e2e (`make e2e`) 3/3. Run the task's own tests and the full suite of the side you touched before committing.
- Accent `#2a4aae` for the active axis and selection only. No all-caps section labels, no explainer line under headings, no emoji icons (inline stroke SVG). Real `<button>`s, `aria-label` on icon-only buttons, primary controls ≥44 px, text contrast ≥4.5:1.
- Image model only through `get_image_provider()`; tests use the mock providers (`IMAGE_PROVIDER=mock`, mock reasoning).
- `DEMO_MODE=1`: note Visualize, take Visualize/Keep, and node Run require the demo unlock (follow how `visualize_option` enforces it); user plugins (from `PLUGINS_DIR`) are never loaded.
- Flags: `PLUGINS_ENABLED` (default true; false → plugin endpoints 404, no Plugins rail icon, no Nodes tool). `EXPLORE_ENABLED` false → Axis tool hidden. The browser learns both from `GET /api/demo/status` (`explore_enabled` exists; Task 5 adds `plugins_enabled` beside it in `backend/app/api/demo.py`, Task 8 adds it to `DemoStatus` and `frontend/src/demo.ts`).
- No new frontend runtime dependencies. No new backend dependencies.
- Generated things are only made on an explicit click (Visualize, Regenerate, Run).
- Commit messages: conventional (`feat(plugins): …`), ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A Python plugin that hangs, crashes, prints non-JSON, or prints >1 MB** → the run ends `failed` with a plain message (`PLUGIN_TIMEOUT`, `PLUGIN_CRASHED`, `PLUGIN_BAD_OUTPUT`) and the node can run again. (Task 6 tests.)
2. **A node input item removed after it was added** → removed inputs are skipped at run time; if fewer than `inputs.min` remain the run fails with `PLUGIN_BAD_INPUT`, and the node card drops the chip. (Task 7, Task 12 tests.)
3. **Server restart mid-run or mid-visualize** → a `running` plugin run / note visualize older than its claim TTL is recoverable (new Run allowed, startup recovery marks it failed). (Task 3, Task 7 tests.)
4. **Typing `n`, `a`, `v` or Delete inside a note, the steer box, or a node param field** → no tool switch, no deletion. (Task 9, Task 10 tests.)
5. **Keep pressed twice, or Keep on take 2 while take 1 is kept** → idempotent; exactly one kept take per option, the other re-staged. (Task 4 tests.)

---

## File Structure

Backend
- `backend/alembic/versions/0007_round2.py` — columns, constraints, plugin tables.
- `backend/app/db/models.py` — new columns/tables/constants.
- `backend/app/notes/{__init__,service,visualize}.py` — create/update notes, note visualize job.
- `backend/app/explore/keep.py` — keep/unkeep takes.
- `backend/app/plugins/{__init__,manifest,registry,runners,shim,service,writeback}.py`, `backend/app/plugins/packs.json`, `backend/app/plugins/builtin/<id>/plugin.json` (+ `main.py` / `prompt.md`).
- `backend/app/api/{notes,plugins}.py` — routes.
- `backend/app/providers/image_gen.py` — `generate`.
- Tests mirror under `backend/tests/unit/...` and `backend/tests/integration/api/...`.

Frontend
- `frontend/src/api.ts`, `queries.ts`, `events.ts` — types, calls, SSE handling.
- `frontend/src/shell/{BoardShell,LeftRail,RailPanel,AgentCard,BottomToolbar,tools}.tsx|ts` — the calm layout.
- `frontend/src/canvas/{NoteNode,NoteEditor,AxisLayer,AxisPopover,ItemChips}.tsx`, `canvas/axis.ts` — notes and axis.
- `frontend/src/plugins/{PluginsPanel,NodeCard,NodesMenu,nodeLogic}.tsx|ts`.
- `frontend/src/pages/BoardPage.tsx` — composes `BoardShell`.
- `frontend/tests/e2e/round2.spec.ts`.

Docs: `docs/plugins.md`, `docs/plugins/examples/{word-count,tagline}/`, README section.

---

### Task 0: Artboard copies for implementers

**Files:** Create `docs/superpowers/specs/round2-artboards/{BoardCalm,NoteNode,ActionNodes,Plugins,Chips}.dc.html`

- [ ] **Step 1:** Copy the five files from `/private/tmp/claude-501/-Users-shivam-Desktop-muse-design-curator/8903b0dc-4eb2-4f4e-a3a7-e4e6370b02c9/scratchpad/artifact-files/3a8ec0a4-afa0-45df-9e1b-92b575d5cd1d/project/` into that folder (they are static HTML-ish mockups; `{{…}}` holes are filled by the `renderVals()` at the bottom of each file).
- [ ] **Step 2:** Record baseline counts: run the full backend and frontend suites; write the numbers into the commit message.
- [ ] **Step 3:** Commit `docs: round 2 artboards for reference`.

---

### Task 1: Migration 0007 and models

**Files:**
- Create: `backend/alembic/versions/0007_round2.py`
- Modify: `backend/app/db/models.py`, `backend/app/api/schemas.py` (`item_to_dict`), `backend/app/db/repos/explore.py` (`option_to_dict`)
- Test: `backend/tests/integration/db/test_migration_0007.py`, `backend/tests/unit/db/test_models_round2.py`

**Interfaces:**
- Produces (models.py):
  - `ITEM_KINDS = ("image", "video", "link", "note")`; `ORIGINS` += `"note"`; `OPTION_STATUS` += `"kept"`; attribute event actor constraint allows `("user", "model", "plugin")`; attribute event action allows `"plugin"` in addition to the current list.
  - `BoardItem.note_text: str | None`, `BoardItem.staged: bool` (default False, server_default `0`).
  - `ExploreOption.kept_item_id: str | None` (no FK, like `explore_option_id`).
  - `BoardPlugin(board_id, plugin_id, added_at)` table `board_plugins`, PK (board_id, plugin_id).
  - `PluginNode` table `plugin_nodes`: `id` (`_id("node")`), `board_id` FK, `plugin_id`, `x,y,w,h` floats, `input_item_ids_json`, `params_json`, `last_run_id` nullable, `removed_at` nullable, `created_at`.
  - `PluginRun` table `plugin_runs`: `id` (`_id("prun")`), `board_id` FK, `node_id` FK, `plugin_id`, `input_item_ids_json`, `params_json`, `status` in `PLUGIN_RUN_STATUS = ("queued","running","done","failed")`, `progress_json`, `output_json`, `error_code`, `error_message`, `claimed_at`, `created_at`, `finished_at`.
  - `item_to_dict` adds `"note_text"`, `"staged"`; `option_to_dict` adds `"kept_item_id"`.
- Register new id prefixes in `backend/app/db/ids.py` if it keeps a prefix list.

- [ ] **Step 1: Failing tests.** `test_migration_0007.py::test_upgrade_on_populated_db` — build a DB at `0006_explore` (use the helper the 0004/0006 migration tests use), insert a board, an image item, an exploration, an option and a generated item with `explore_option_id`; upgrade to head; assert the rows survive, `staged == 0` on both items, `kept_item_id IS NULL`, and inserting an item with `kind='note', origin='note'` succeeds. `::test_downgrade_roundtrip` — downgrade to `0006_explore` and back up with no error. `test_models_round2.py::test_note_item_and_plugin_rows` — create a note item, a `PluginNode`, a `PluginRun(status="queued")` via the ORM; a `PluginRun(status="bogus")` raises `IntegrityError`.
- [ ] **Step 2:** Run `cd backend && uv run pytest tests/integration/db/test_migration_0007.py tests/unit/db/test_models_round2.py -q` → FAIL.
- [ ] **Step 3:** Write the migration (`revision="0007_round2"`, `down_revision="0006_explore"`). Table rebuilds (SQLite batch mode for changed check constraints) must follow the FK-deferral pattern `0006_explore` and `backend/alembic/env.py` use. Update models and dict functions.
- [ ] **Step 4:** Re-run → PASS; run full backend suite → all pass.
- [ ] **Step 5:** Commit `feat(db): round 2 migration (notes, staged takes, plugin tables)`.

---

### Task 2: Notes backend

**Files:**
- Create: `backend/app/notes/__init__.py`, `backend/app/notes/service.py`, `backend/app/api/notes.py`
- Modify: `backend/app/main.py` (router), `backend/app/api/items.py` (`patch_item` accepts `note_text` for notes), `backend/app/extraction/service.py` (parse guard), board profile/signals/retrieval/compare entry points that iterate board items (find them with `grep -rn "BoardItem.kind\|kind ==\|removed_at.is_(None)" backend/app/board backend/app/retrieval backend/app/runs backend/app/explore`), the reasoning prompt builders that include board title/context (`grep -rn "context" backend/app/explore/prompts.py backend/app/extraction`)
- Test: `backend/tests/unit/notes/test_service.py`, `backend/tests/integration/api/test_notes.py`

**Interfaces:**
- Produces:
  - `create_note(session, board_id: str, text: str, x: float, y: float, w: float | None = None, h: float | None = None) -> BoardItem` — `kind="note"`, `origin="note"`, `rights_status="user_supplied"`, `parse_status="completed"`, default `w=220`, `h=150`; publishes `item.added` after commit.
  - `update_note_text(session, item_id: str, text: str) -> BoardItem` — 400 `NOT_A_NOTE` on non-notes; publishes `item.updated`.
  - `board_notes_context(session, board_id: str, max_notes: int = 20, max_chars: int = 2000) -> list[str]` — newest first, non-removed, non-empty, truncated to the char cap.
  - `POST /api/boards/{board_id}/notes` body `{text: str (1..2000), x, y, w?, h?}` → 201 item dict. `PATCH /api/items/{id}` with `{"note_text": "..."}`.
- Consumes: Task 1 columns.

- [ ] **Step 1: Failing tests.**
  - `test_create_note_defaults` (kind/origin/rights/parse_status/w/h).
  - `test_update_note_text_rejects_image` → `AppError` 400 `NOT_A_NOTE`.
  - `test_parse_item_skips_notes` — calling `parse_item` on a note returns without calling the reasoning provider and leaves `parse_status="completed"`.
  - `test_profile_ignores_notes` — board with 2 images + 1 note: profile item count is 2.
  - `test_notes_context_caps` — 25 notes → 20 returned, total chars ≤ 2000, newest first.
  - `test_explore_prompt_includes_notes` — the explore prompt text for a board with a note "honey, like old paper" contains that text.
  - API: `test_post_note_201`, `test_post_note_empty_text_422`, `test_patch_note_text`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; exclude `kind == "note"` everywhere items feed image work (profile, signals, retrieval pool/board embeddings, compare, explore source validation → explore on a note is 400 `NOT_AN_IMAGE`). Add notes to reasoning context as a "Notes on the board:" block.
- [ ] **Step 4:** Re-run → PASS; full backend suite → pass.
- [ ] **Step 5:** Commit `feat(notes): note items, excluded from image work, read as context`.

---

### Task 3: Image generate + note Visualize

**Files:**
- Modify: `backend/app/providers/image_gen.py`, `backend/app/explore/check.py` (expose a target-only check), `backend/app/main.py` (startup recovery call if visualize recovery lives there)
- Create: `backend/app/notes/visualize.py`
- Modify: `backend/app/api/notes.py`
- Test: `backend/tests/unit/providers/test_image_generate.py`, `backend/tests/unit/notes/test_visualize.py`, `backend/tests/integration/api/test_note_visualize.py`

**Interfaces:**
- Produces:
  - `ImageProvider.generate(self, prompt: str) -> bytes` on the protocol, `MuseImageProvider` (`POST /v1/images/generations`, JSON `{model, prompt}`, read `data[0].b64_json`, same reliability wrapper as `edit`) and `MockImageProvider` (deterministic 768×768 PNG whose colour derives from a hash of the prompt).
  - `note_prompt(note_text: str, board_title: str, board_context: str | None) -> str` — starts from `"{note}. Board: {title} — {context}. Product photo, plain background."` (omit the board part cleanly when empty).
  - `request_note_visualize(session, note_id: str) -> None` — 404 not found, 400 `NOT_A_NOTE`, 409 `NOTE_VISUALIZING` while a claim younger than `CLAIM_TTL_S` (reuse 300 s) exists. Claim stored in the note's `generation_json` as `{"visualizing_since": iso}` (no new column).
  - Job `"visualize_note"`: generate → generated item (`origin="generated"`, `rights_status="generated"`, `parent_item_id=note.id`, `generation_json={"model":..., "prompt":..., "from":"note"}`), placed at `x = note.x + note.w + 40`, `y` = note.y plus the stacked heights (+24 gap) of earlier images from this note; then `parse_item`, then `check_target_only(...)` stored in `check_json` as `{"target_ok": bool|None, "answer": str}`; clears the claim; events `note.visualizing`, `item.added`, `item.updated`, `note.visualized` / `note.visualize_failed` with `{note_id, item_id?, error?}`.
  - `recover_stuck_notes(session) -> int` called where `visualize.recover_stuck` is called at startup.
  - `POST /api/items/{note_id}/visualize` → 202 `{"note_id", "status": "visualizing"}`.

- [ ] **Step 1: Failing tests.** `test_mock_generate_deterministic` (same prompt → same bytes, valid PNG); `test_muse_generate_request_shape` (mock HTTP transport as the `edit` tests do; asserts path and JSON); `test_note_prompt_with_and_without_context`; `test_visualize_note_creates_generated_item_beside_note` (position, parent, rights); `test_second_visualize_stacks_below`; `test_visualize_conflict_409_then_stale_claim_allowed` (set claim 301 s in the past → allowed); `test_failure_leaves_no_item_and_clears_claim` (mock provider raising `ModelError` → event `note.visualize_failed`); `test_demo_mode_requires_unlock`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement following `explore/visualize.py`'s structure (claim with conditional update, `after_commit` publishes, job registration).
- [ ] **Step 4:** Re-run → PASS; full backend suite.
- [ ] **Step 5:** Commit `feat(notes): visualize a note (text to image), check the result`.

---

### Task 4: Staged takes, Keep and Un-keep

**Files:**
- Create: `backend/app/explore/keep.py`
- Modify: `backend/app/explore/visualize.py` (`_ingest`: `staged=True`, stop placing beside the note — place at the source's position, it is not drawn), `backend/app/api/explore.py` (routes), profile/signals/retrieval/compare exclusions (`staged == False`), `backend/app/explore/service.py` (`resting_status` knows `kept`)
- Test: `backend/tests/unit/explore/test_keep.py`, `backend/tests/integration/api/test_keep.py`

**Interfaces:**
- Produces:
  - `keep_take(session, option_id: str, item_id: str, at: tuple[float, float] | None = None) -> ExploreOption` — 404 option/item; 400 `NOT_A_TAKE` if `item.explore_option_id != option_id`; un-stages `item`, re-stages the previous `kept_item_id` take (if different), sets `kept_item_id`, `status="kept"`, moves the item to `at` when given; idempotent when already kept; publishes `item.updated` for each changed item and the exploration event.
  - `unkeep(session, option_id: str) -> ExploreOption` — re-stages the kept take, clears `kept_item_id`, `status="visualized"`; no-op when nothing kept.
  - `POST /api/options/{id}/keep` body `{item_id, x?, y?}`; `POST /api/options/{id}/unkeep`. Both demo-locked like visualize.
  - Option dict includes `takes: [item_id...]` (staged or kept items with this `explore_option_id`, oldest first) so the popover can page them without loading hidden items separately.

- [ ] **Step 1: Failing tests.** `test_visualize_creates_staged_take`; `test_keep_unstages_and_sets_kept`; `test_keep_twice_idempotent`; `test_keep_second_take_restages_first`; `test_unkeep_restages`; `test_keep_wrong_option_400`; `test_profile_ignores_staged_items`; `test_existing_unstaged_takes_untouched` (pre-existing take with `staged=False` stays visible and is listed in `takes`); `test_option_dict_lists_takes`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Re-run → PASS; full suite.
- [ ] **Step 5:** Commit `feat(explore): staged takes with keep and un-keep`.

---

### Task 5: Plugin manifests, discovery, packs, install

**Files:**
- Create: `backend/app/plugins/__init__.py`, `manifest.py`, `registry.py`, `packs.json`, `backend/app/plugins/builtin/{image,palette,critique,video,mesh,code,webfill,frames,langcard,techpack,bom,compare,texture,cleanup}/plugin.json`, `backend/app/api/plugins.py`
- Modify: `backend/app/config.py` (`PLUGINS_ENABLED: bool = True`, `PLUGINS_DIR: str = "data/plugins"`, `PLUGIN_TIMEOUT_S: int = 30`, `VIDEO_MODEL`, `MESH_MODEL`, `CODE_SANDBOX` optional strs), `backend/app/main.py`, `.env.example`, `.gitignore` (`data/plugins/`)
- Test: `backend/tests/unit/plugins/test_manifest.py`, `test_registry.py`, `backend/tests/integration/api/test_plugins_api.py`

**Interfaces:**
- Produces (`manifest.py`):
  - `class Manifest` (pydantic): `id` (`^[a-z][a-z0-9_-]{1,31}$`), `name`, `description`, `mark` (≤4 chars), `tint`, `ink`, `runner: Literal["python","llm","model"]`, `runs_on`, `inputs: InputSpec(kinds: list[Literal["image","video","note","link"]], min: int = 1, max: int = 12)`, `params: dict` (JSON Schema object, default `{"type":"object","properties":{}}`), `outputs: list[Literal["images","notes","attributes","text","table"]]`, `requires: list[str] = []`, `entry: str | None`, `prompt: str | None`, `output_schema: dict | None`, `model: Literal["image.edit","image.generate","video.generate","mesh.from_image"] | None`, `secondary: str | None` (label of the card's second button). Validators: python needs `entry`; llm needs `prompt` + `output_schema`; model needs `model`.
  - `load_manifest(folder: Path, *, builtin: bool) -> Manifest` — raises `ManifestError(reason)`; user (non-builtin) manifests with `runner="model"` are rejected.
  - `to_tool(m: Manifest) -> dict` → `{"name": m.id, "description": m.description, "input_schema": {"type":"object","properties":{"item_ids":{"type":"array","items":{"type":"string"},"minItems": m.inputs.min,"maxItems": m.inputs.max},"params": m.params},"required":["item_ids"]}}`.
- Produces (`registry.py`):
  - `@dataclass Plugin(manifest: Manifest, folder: Path, builtin: bool)`; `status(p) -> Literal["available","not_connected"]` (any `requires` setting unset → not_connected; `model` runner `video.generate`/`mesh.from_image` → not_connected).
  - `discover(settings) -> tuple[dict[str, Plugin], list[dict]]` (plugins by id, skipped `[{folder, reason}]`); built-ins first, user folder skipped when `DEMO_MODE`; a user id equal to a built-in id is skipped with reason `"shadows a built-in"`.
  - `get_registry() -> dict[str, Plugin]` (cached), `reload() -> dict` (`{"loaded": [...ids], "skipped": [...]}`).
  - `load_packs() -> list[dict]` → `[{id, name, about, plugin_ids}]`, unknown ids dropped, plus `{"id":"all", "name":"All plugins", "about":"Everything available.", "plugin_ids": sorted(all)}` last.
- API (all 404 when `PLUGINS_ENABLED` false): `GET /api/plugins` → `{"plugins": [plugin_to_dict]}` where `plugin_to_dict = {id,name,description,mark,tint,ink,runner,runs_on,inputs,params,outputs,secondary,status,builtin}`; `GET /api/plugin-packs`; `POST /api/plugins/reload`; `GET /api/boards/{id}/plugins` → `{"plugin_ids": [...]}`; `POST /api/boards/{id}/plugins` `{plugin_id}` (404 unknown id; idempotent); `DELETE /api/boards/{id}/plugins/{plugin_id}` (204).
- Built-in manifests and packs: copy names, `does` text, marks, tints and `runs_on` from `round2-artboards/Plugins.dc.html` (`N` and `P` objects) and the ten "More nodes" from `ActionNodes.dc.html`. `image`: `runner="model"`, `model="image.edit"`, params `{mode: enum ["part","whole"] default "part", part: string default "", prompt: string, count: integer 1–4 default 1}`, inputs `["image","note"]`, outputs `["images"]`, `secondary="Prompt"`. `palette`: python, `entry="main.py"`, params `{count: integer 3–8 default 5}`, outputs `["notes","attributes"]`. `critique`: llm, inputs `["image","note","video","link"]` min 1, outputs `["notes","text"]`, `output_schema` `{points:[{verdict: enum fits|misses|unclear, text}], summary}`. Placeholders: `video` (model `video.generate`, `requires: ["VIDEO_MODEL"]`, `secondary="Track with SAM"`), `mesh` (model `mesh.from_image`, `requires: ["MESH_MODEL"]`, `secondary="Download"`), `code` (python, `requires: ["CODE_SANDBOX"]`, `secondary="Edit code"`), the rest `runner="llm"` with `requires: ["PLUGIN_PLACEHOLDER"]` (a setting that never exists) and a minimal prompt/schema so they validate. Palette/critique files are added in Task 6/7; give them placeholder `main.py`/`prompt.md` now so manifests validate.

- [ ] **Step 1: Failing tests.** `test_manifest_python_requires_entry`; `test_manifest_llm_requires_prompt_and_schema`; `test_user_manifest_model_runner_rejected`; `test_bad_id_rejected`; `test_every_builtin_loads_and_converts_to_tool` (loop all builtin folders; `to_tool` output has `name`, `input_schema.properties.item_ids`); `test_discover_skips_invalid_with_reason` (tmp user dir with a broken JSON); `test_user_cannot_shadow_builtin`; `test_demo_mode_skips_user_plugins`; `test_status_not_connected_when_requires_unset`; `test_packs_drop_unknown_and_append_all`; API: `test_list_plugins`, `test_board_add_remove_plugin_idempotent`, `test_add_unknown_plugin_404`, `test_plugins_disabled_404`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS; full suite.
- [ ] **Step 5:** Commit `feat(plugins): manifests, discovery, packs, per-board install`.

---

### Task 6: Plugin runners

**Files:**
- Create: `backend/app/plugins/runners.py`, `backend/app/plugins/shim.py`, `backend/app/plugins/builtin/palette/main.py` (+ `palette_core.py` vendored pure functions), `backend/app/plugins/builtin/critique/prompt.md`
- Modify: `backend/app/providers/reasoning.py` (add `structured(images, schema, prompt) -> dict` to the protocol and the three providers if `extract` cannot be reused without its extraction assumptions; mock returns schema-shaped deterministic output — reuse `MockReasoningProvider._make`)
- Test: `backend/tests/unit/plugins/test_runners.py`, `backend/tests/unit/plugins/test_palette_plugin.py`

**Interfaces:**
- Produces:
  - `@dataclass RunInput(id: str, kind: str, label: str, attributes: dict[str, Any], note_text: str | None, image: bytes | None)`; `@dataclass BoardCtx(title: str, context: str | None, notes: list[str])`.
  - `class PluginError(Exception)` with `code: str` (`PLUGIN_TIMEOUT`, `PLUGIN_CRASHED`, `PLUGIN_BAD_OUTPUT`, `PLUGIN_BAD_INPUT`, `PLUGIN_NOT_CONNECTED`, `PLUGIN_MODEL_FAILED`) and `message: str` (plain words).
  - `run_plugin(plugin: Plugin, inputs: list[RunInput], params: dict, board: BoardCtx, progress: Callable[[str], None]) -> dict` — validates inputs (kinds, min/max) and params (`jsonschema`-free: check required keys, types and enum/min/max for the simple types the manifests use; fill defaults), dispatches, validates output with `validate_output(manifest, out) -> dict` (only declared output kinds; shape per spec "Validate output"; images as `{"data_b64": str, "caption": str}`).
  - Python runner: `subprocess.run([sys.executable, "-I", str(SHIM), str(plugin.folder)], input=json, capture_output=True, timeout=settings.PLUGIN_TIMEOUT_S, cwd=tmpdir, env={"PATH": os.environ["PATH"], "HOME": tmpdir, "PYTHONHASHSEED": "0"})`; images written to `tmpdir/in/<id>.png` and passed as `image_path`; stdout capped at 1 MB (`PLUGIN_BAD_OUTPUT` "output too large"); non-zero exit → `PLUGIN_CRASHED` with the last 4 KB of stderr; timeout → `PLUGIN_TIMEOUT`.
  - `shim.py`: reads stdin JSON, imports `<folder>/<entry>` by path, calls `run(inputs, params, ctx)` where `inputs` is the list of dicts, `ctx = {"board": {...}}`, prints `json.dumps(result)`.
  - LLM runner: renders `prompt` replacing `{{params.<k>}}`, `{{notes}}` (newline-joined input note texts + board notes), `{{board.title}}`, `{{board.context}}`; calls `get_reasoning_provider().structured(images, output_schema, prompt)`; maps manifest outputs: `notes` ← `points` → `[{"text": f"{verdict}: {text}"}]` for critique — generically: the llm output is passed through `validate_output` as-is when its keys match output kinds, else the plugin's `output_schema` must already be shaped as `{notes?, attributes?, text?, table?}` (critique's schema keeps `points`; the critique manifest declares a `map` of `{"notes": "points", "text": "summary"}` — add optional `output_map: dict[str, str] | None` to `Manifest`).
  - Model runner: `image.edit` → for each image input (cap `count`), prompt `"Change only the {part}: {prompt}. Keep everything else exactly the same."` (mode part) or the prompt plus appended note texts (whole); `image.generate` when there are no image inputs; video/mesh → `PLUGIN_NOT_CONNECTED`; provider `ModelError` → `PLUGIN_MODEL_FAILED`.
  - Palette `main.py::run(inputs, params, ctx)` → `{"notes": [{"text": "Palette: #aabbcc, …"}], "attributes": [{"item_id": i["id"], "key": "palette", "label": "Palette", "value": "#aabbcc, …"}]}` using the vendored k-means/Lab logic from `app/measure/palette.py` (may import numpy/PIL/scikit-learn).

- [ ] **Step 1: Failing tests** (python tests write tiny plugins into `tmp_path`): `test_python_plugin_roundtrip`; `test_python_plugin_timeout` (`time.sleep(5)` with timeout setting 1 → `PLUGIN_TIMEOUT`); `test_python_plugin_crash_reports_stderr`; `test_python_plugin_non_json_output`; `test_python_plugin_output_too_large`; `test_python_env_is_stripped` (plugin returns `os.environ` keys → subset of `{"PATH","HOME","PYTHONHASHSEED"}` plus interpreter-set ones like `__CF_USER_TEXT_ENCODING`/`LC_CTYPE` — assert no key containing `KEY`, `TOKEN`, `SECRET` and no `MUSE_`/`META_` prefixes); `test_output_kind_not_declared_rejected`; `test_input_kind_and_count_checked`; `test_params_defaults_and_bounds`; `test_llm_runner_renders_prompt_and_maps_output` (mock provider); `test_model_runner_part_prompt` (mock image provider records prompt); `test_video_not_connected`; `test_palette_plugin_deterministic` (two runs on a fixture image → same hexes, `count` respected).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS; full suite.
- [ ] **Step 5:** Commit `feat(plugins): python, llm and model runners; palette and critique built-ins`.

---

### Task 7: Nodes, runs, write-back, docs

**Files:**
- Create: `backend/app/plugins/service.py`, `backend/app/plugins/writeback.py`, `docs/plugins.md`, `docs/plugins/examples/word-count/{plugin.json,main.py}`, `docs/plugins/examples/tagline/{plugin.json,prompt.md}`
- Modify: `backend/app/api/plugins.py`, `backend/app/main.py` (startup recovery), `backend/app/extraction/merge.py` (treat `source="plugin"` like user values on re-extraction), README (short "Plugins" section linking `docs/plugins.md`)
- Test: `backend/tests/unit/plugins/test_service.py`, `test_writeback.py`, `backend/tests/integration/api/test_nodes_api.py`, `backend/tests/unit/plugins/test_examples.py`

**Interfaces:**
- Consumes: Task 5 registry, Task 6 `run_plugin`, `RunInput`, `BoardCtx`, `PluginError`; Task 2 `create_note`, `board_notes_context`.
- Produces:
  - `create_node(session, board_id, plugin_id, x, y, input_item_ids: list[str]) -> PluginNode` — 400 `PLUGIN_NOT_ADDED` unless in `board_plugins`; `w=300`, `h=360`; params = manifest defaults; `node_to_dict(n) -> {id, board_id, plugin_id, x, y, w, h, input_item_ids, params, last_run_id}`.
  - `update_node(session, node_id, *, x=None, y=None, input_item_ids=None, params=None) -> PluginNode` (params validated); `remove_node(session, node_id) -> None` (soft, `removed_at`).
  - `request_run(session, node_id) -> PluginRun` — 404; demo lock; 409 `NODE_RUNNING` when the node's latest run is queued/running with `claimed_at` younger than `max(PLUGIN_TIMEOUT_S*2, 120)` s; 400 `PLUGIN_NOT_CONNECTED` when status not available; creates run (`queued`), sets `last_run_id`, enqueues job `"plugin_run"`; event `plugin_run.queued`.
  - Job `plugin_run(run_id)`: mark `running` + `claimed_at`, load inputs skipping removed items (fewer than `min` → `PLUGIN_BAD_INPUT` "Some inputs were removed"), `run_plugin(... progress=...)` (progress → `progress_json` + `plugin_run.progress` event), `apply_output(session, run, node, out) -> dict` (writeback), `done` with `output_json` = `{text?, table?, created_item_ids, skipped_attributes}`; on `PluginError` → `failed` with code/message, event `plugin_run.failed`; on unexpected exception → `failed` `PLUGIN_CRASHED` "Something went wrong".
  - `recover_stuck_runs(session) -> int` — at startup, `queued|running` runs → `failed` `PLUGIN_INTERRUPTED`.
  - `writeback.apply_output`: images → generated items (`generation_json={"plugin": id, "model": runs_on, "run_id": run.id}`, `parent_item_id` = first image input or None) and notes → `create_note`; placed in a column at `x = node.x + node.w + 40`, stacking down from `node.y` with 24 gaps; attributes → upsert per spec "Plugin attributes" (skip when existing `source == "user"` or status in `("edited","confirmed")`, report in `skipped_attributes`; `AttributeEvent(actor="plugin", action="plugin")`); events `item.added`, `attributes.updated` (use the event name the attributes API already publishes), `plugin_run.done` `{node_id, run_id, output}`.
  - API: `GET /api/boards/{id}/nodes` → `{"nodes":[...], "runs": {node_id: run_to_dict}}` (latest run per node); `POST /api/boards/{id}/nodes` `{plugin_id, x, y, input_item_ids}` → 201; `PATCH /api/nodes/{id}`; `DELETE /api/nodes/{id}` 204; `POST /api/nodes/{id}/run` → 202 run dict; `GET /api/plugin-runs/{run_id}`. `run_to_dict = {id, node_id, plugin_id, status, progress, output, error_code, error_message, created_at, finished_at}`.
  - Docs: `docs/plugins.md` — what a plugin is, folder layout, manifest fields table, python I/O contract (stdin/stdout JSON, `run(inputs, params, ctx)`), llm prompt placeholders and `output_map`, outputs shape, `POST /api/plugins/reload`, the trust warning ("runs on your machine with your permissions; not a sandbox; never loaded in demo mode"), dependency rule (app's Python, no extra packages).

- [ ] **Step 1: Failing tests.** `test_create_node_requires_added_plugin`; `test_run_palette_end_to_end_writes_note_and_attributes` (JOBS_SYNC; asserts note text starts "Palette:", attribute `palette` on input with `source="plugin"`); `test_run_image_plugin_creates_generated_items_with_lineage`; `test_writeback_skips_user_edited_attribute`; `test_reextraction_keeps_plugin_attribute`; `test_removed_input_skipped_and_below_min_fails`; `test_run_conflict_409_and_stale_allowed`; `test_not_connected_plugin_run_400`; `test_recover_stuck_runs_marks_interrupted`; `test_failed_run_event_and_rerun_allowed`; `test_demo_mode_run_requires_unlock`; `test_examples_load_and_run` (copy `docs/plugins/examples/*` into a tmp `PLUGINS_DIR`, reload, run word-count on a note → note "N words").
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS; full backend suite and lint.
- [ ] **Step 5:** Commit `feat(plugins): nodes and runs, write-back with lineage, docs and examples`.

---

### Task 8: Frontend data layer

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/queries.ts`, `frontend/src/events.ts`, `frontend/src/test/fixtures.ts`
- Test: `frontend/src/api.test.ts`, `frontend/src/events.test.ts`

**Interfaces:**
- Produces (api.ts): `ItemKind` += `'note'`; `Item.note_text: string | null`, `Item.staged: boolean`; `ExploreOption.kept_item_id: string | null`, `ExploreOption.takes: string[]`, status union += `'kept'`; types `PluginInfo`, `PluginPack`, `PluginNode`, `PluginRun` (fields exactly as the backend dicts in Tasks 5 and 7); functions `createNote(boardId, body: {text, x, y, w?, h?})`, `patchNoteText(itemId, text)` (via `patchItem`), `visualizeNote(itemId)`, `keepTake(optionId, itemId, at?: Point)`, `unkeepTake(optionId)`, `listPlugins()`, `listPacks()`, `listBoardPlugins(boardId)`, `addBoardPlugin(boardId, pluginId)`, `removeBoardPlugin(boardId, pluginId)`, `listNodes(boardId)`, `createNode(boardId, body)`, `patchNode(nodeId, body)`, `deleteNode(nodeId)`, `runNode(nodeId)`; `keys` += `plugins()`, `packs()`, `boardPlugins(id)`, `nodes(id)`.
- queries.ts: `usePlugins()`, `usePacks()`, `useBoardPlugins(boardId)`, `useNodes(boardId)`, and `visibleItems(items: Item[]): Item[]` (drops `staged`).
- events.ts: `EVENT_TYPES` += `note.visualizing`, `note.visualized`, `note.visualize_failed`, `plugin_run.queued`, `plugin_run.progress`, `plugin_run.done`, `plugin_run.failed`; `applyEvent` updates the `nodes` cache's `runs[node_id]` on `plugin_run.*`, and keeps a small per-board `noteVisualizing` set in a store exported as `noteVisualizeStore` (`useNoteVisualizing(noteId): boolean`) cleared on visualized/failed. Also export `boardActivity` store: last 50 `{at, text}` entries built from SSE events and telemetry actions, with `describeEvent(type, data): string | null` (plain sentences, e.g. "Palette finished: 1 note added", "Honey visualized").
- [ ] **Step 1: Failing tests.** `api.test.ts`: request path/method/body for each new function (follow existing style). `events.test.ts`: `test plugin_run.done updates node run`, `test note.visualized clears visualizing`, `test describeEvent sentences`, `test visibleItems drops staged`.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/api.test.ts src/events.test.ts` → FAIL. **Step 3:** Implement. **Step 4:** PASS; `npm test`; `npx tsc -b`.
- [ ] **Step 5:** Commit `feat(frontend): data layer for notes, takes, plugins and nodes`.

---

### Task 9: Calm board shell

**Files:**
- Create: `frontend/src/shell/BoardShell.tsx`, `LeftRail.tsx`, `RailPanel.tsx`, `AgentCard.tsx`, `BottomToolbar.tsx`, `tools.ts`, `shell.css` (or add to `index.css` following its conventions)
- Modify: `frontend/src/pages/BoardPage.tsx` (compose `BoardShell`; move ContextBar/AddMenu/BoardSignals/LensReview/Onboarding/DemoBadge/UploadStatus into their new homes), `frontend/src/pages/shortcutGuard.ts` (tools shortcuts), `frontend/src/panels/AddMenu.tsx` (split search into a component the Search rail panel can render, if it isn't already)
- Test: `frontend/src/shell/BoardShell.test.tsx`, `tools.test.ts`, `AgentCard.test.tsx`

**Interfaces:**
- Produces:
  - `tools.ts`: `type Tool = 'select' | 'note' | 'axis'`; `toolStore` with `useTool(): Tool`, `setTool(t)`; `toolForKey(key: string, flags: {explore: boolean}): Tool | null` (`n`→note, `a`→axis when explore, `Escape`→select).
  - `LeftRail` props `{open: RailId | null, onOpen(id: RailId | null), plugins: boolean}`; `type RailId = 'library' | 'search' | 'plugins' | 'vocabulary'`. Buttons 40×40 in a 56 px rail, `aria-label`s "Library", "Search", "Plugins", "Vocabulary", `aria-pressed` for the open one.
  - `RailPanel` — slide-out beside the rail, `role="dialog"` `aria-label` = rail name, `Esc` closes; content: library → items list (thumbnail + label; click selects and centres) + Add actions + `BoardSignals` + `LensReview` when proposed; search → the existing search UI; plugins → `<PluginsPanel/>` slot (Task 12 provides it; render a stub until then); vocabulary → "Vocabulary is coming soon."
  - `AgentCard` props `{boardId}` — "Muse", latest `boardActivity` text (or "Nothing yet."), disabled input placeholder "Agent coming soon" with a visually hidden label, expand button (`aria-label="Show activity"`) toggling the list of last 50 entries; hidden while the right drawer is open.
  - `BottomToolbar` props `{onNodes(): void, plugins: boolean, explore: boolean}` — Select, Note, Axis (hidden when explore off), Nodes (hidden when plugins off; opens `NodesMenu` from Task 12, stub until then), `aria-pressed` on the active tool.
  - Header as in `BoardCalm` (back link, title, context sentence) reusing `ContextBar` editing.
- [ ] **Step 1: Failing tests.** `tools.test.ts`: key mapping incl. explore off. `BoardShell.test.tsx`: renders rail with 4 buttons (3 when plugins off); opening Library shows the items list; `Esc` closes the panel; `n` while focus is in a `<textarea>` does not change the tool; Inspect drawer opening hides the agent card. `AgentCard.test.tsx`: shows latest activity; input disabled; expand lists entries.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement; keep every existing panel reachable (Review Focus / anti-goal). **Step 4:** PASS; `npm test` (fix tests of moved components by updating their render location, not their behaviour); `npm run lint`; `npx tsc -b`.
- [ ] **Step 5:** Commit `feat(frontend): calm board shell with slim rails, agent card and tools`.

---

### Task 10: Notes on the canvas

**Files:**
- Create: `frontend/src/canvas/NoteNode.tsx`, `frontend/src/canvas/NoteEditor.tsx`, `frontend/src/canvas/NoteBar.tsx`
- Modify: `frontend/src/canvas/Canvas.tsx` (render notes from items with `kind==='note'`; note tool click creates; staged items filtered with `visibleItems`), `frontend/src/canvas/ItemNode.tsx` (generated-from-note placeholder card while visualizing), `frontend/src/canvas/history.ts` usage for create/edit/delete
- Test: `frontend/src/canvas/NoteNode.test.tsx`, `NoteEditor.test.tsx`

**Interfaces:**
- Consumes: Task 8 `createNote`, `patchItem`, `visualizeNote`, `useNoteVisualizing`; Task 9 `useTool`, `setTool`.
- Produces: `NoteNode` (Konva group: `#fff6d9` rect radius 4, shadow, text `#3a3220` 14 px IBM Plex Sans, width 220, height grows with text, min 96); `NoteEditor` (HTML `<textarea aria-label="Note">` overlaid at the note's screen bounds; `Esc`/blur saves; empty new note is discarded, empty edit of an existing note restores the old text); `NoteBar` (HTML overlay under a hovered/selected note: **Visualize** button with sparkle SVG, `⋯` menu with Delete and "Send to node" listing added plugins whose `inputs.kinds` includes `note` — choosing one calls Task 12's `addToNode`/create node, stub until then). While `useNoteVisualizing(id)`: a 190×150 placeholder card with progress bar beside the note and a dashed lineage line; generated items with `parent_item_id === note.id` get a solid line.
- [ ] **Step 1: Failing tests.** Note tool click → `createNote` called with canvas coords and editor opens; typing then `Esc` → `patchItem` with `note_text`; empty new note → `deleteItem`, no residue; typing `n`/`a`/Delete inside the editor doesn't switch tools or delete; Visualize disabled when text empty; Visualize → `visualizeNote` and placeholder shows; undo after create removes the note.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS; `npm test`; lint; tsc.
- [ ] **Step 5:** Commit `feat(canvas): notes with in-place editing and visualize`.

---

### Task 11: Text-first axis and chips on the selected item

**Files:**
- Create: `frontend/src/canvas/axis.ts`, `frontend/src/canvas/AxisLayer.tsx`, `frontend/src/canvas/AxisPopover.tsx`, `frontend/src/canvas/ItemChips.tsx`
- Modify: `frontend/src/canvas/Canvas.tsx` (replace `OptionNote` rendering/`placedNotes` with `AxisLayer`; moving a source also moves its kept items in the same undo entry), `frontend/src/panels/ExplorePanel.tsx` (stays in sync; hover highlight targets axis cards), delete `OptionNote.tsx`/`notes.ts` only if nothing else imports them (update their tests accordingly)
- Test: `frontend/src/canvas/axis.test.ts`, `AxisLayer.test.tsx`, `AxisPopover.test.tsx`, `ItemChips.test.tsx`

**Interfaces:**
- Consumes: `useExplorations`, `exploreItem`, `visualizeOption`, `keepTake`, `unkeepTake`, `patchOption` (dismiss), `findRealRequest`, `optionTree`; Task 9 tools (axis tool on a selected image opens the attribute picker = ExplorePanel's attribute list in a popover anchored at the source's right edge).
- Produces:
  - `axis.ts`: `AXIS_GAP_X = 40`, `ROW_H = 132`, `CARD_W = 104`, `CARD_GAP = 9`; `axisRows(source: Bounds, explorations: Exploration[]): AxisRow[]` with `AxisRow = {exploration_id, key, label, y, x0, x1, cards: {option_id, x, y, w, h}[]}` — rows stacked from `source.y` down in exploration `created_at` order; only non-dismissed top-level options (branches render inside the popover); line from `source.x + source.width + AXIS_GAP_X`; `keptSlot(row, option_id): Point` for Keep's `at`.
  - `AxisLayer` props `{items, explorations, selectedId}` — line (accent when the row's source is selected, `#9aa3b0` otherwise), label above, end handle; text cards (name 13.5 px/600, description 11.5 px, small distance dot: near `#9aa3b0`, bold `#566170`, wild `#14181e`); kept cards show the kept item thumbnail (84×84) + "Name · kept" with "· kept" in `#2c7a4b`; end handle opens More / Further / steer.
  - `AxisPopover` props `{option, exploration, source}` — states: not visualized ("**Name**: desc", "Keeps …. Only ‹label› changes.", Visualize, Branch, Find real examples, Dismiss); visualizing (progress); has takes (image of current take, "Name · take n", take pager ‹ ›, Keep/Un-keep, Regenerate, verdict line from `check`).
  - `ItemChips` props `{item}` — for the selected image only, up to 6 chips from `useAttributes`, each with the source mark from `round2-artboards/Chips.dc.html` (`sources` list: measured/read/estimated/web/you/unknown); click → `exploreItem(item.id, {key, mode:'initial'})` and selects that axis.
- [ ] **Step 1: Failing tests.** `axis.test.ts`: two explorations → two rows 132 px apart; dismissed options excluded; card x positions evenly spaced from x0; `keptSlot` equals the card's position. `AxisPopover.test.tsx`: Visualize calls `visualizeOption`; with 2 takes the pager shows "take 2"; Keep calls `keepTake(option.id, take2, keptSlot)`; kept option shows Un-keep → `unkeepTake`; Regenerate calls `visualizeOption` again. `AxisLayer.test.tsx`: kept option renders thumbnail label "Honey · kept". `ItemChips.test.tsx`: max 6 chips, only for the selected image, chip click explores. Moving the source moves kept items (Canvas test with history: undo restores both).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS; `npm test`; lint; tsc.
- [ ] **Step 5:** Commit `feat(canvas): text-first axis with staged takes, keep, and chips on the selected item`.

---

### Task 12: Plugins panel, Nodes menu, node cards

**Files:**
- Create: `frontend/src/plugins/PluginsPanel.tsx`, `NodesMenu.tsx`, `NodeCard.tsx`, `nodeLogic.ts`, `NodeLayer.tsx`
- Modify: `frontend/src/shell/RailPanel.tsx`, `frontend/src/shell/BottomToolbar.tsx`, `frontend/src/canvas/NoteBar.tsx` (Send to node), `frontend/src/canvas/Canvas.tsx` (render `NodeLayer`; dropping items onto a node adds inputs; lineage lines node-inputs → outputs via `generation.run_id`)
- Test: `frontend/src/plugins/PluginsPanel.test.tsx`, `NodeCard.test.tsx`, `nodeLogic.test.ts`

**Interfaces:**
- Consumes: Task 8 plugin/node APIs and queries; `selection` store.
- Produces:
  - `nodeLogic.ts`: `paramFields(schema): Field[]` (`{key, label, type: 'string'|'enum'|'integer'|'boolean'|'json', options?, min?, max?, default?, showIf?}`; image's `part` has `showIf: {mode: 'part'}` derived from a manifest-level convention: a property with `"x-show-if": {"mode": "part"}` — add that key to the image manifest in this task); `summaryLine(plugin, params): string` (image part → "Change only the ‹part›", whole → "Whole image"; others: first param `label value`); `acceptsItem(plugin, item): boolean`; `canRun(plugin, node, items): {ok: boolean, reason?: string}` (status, min/max, removed inputs).
  - `addToNode(qc, nodeId, itemIds)` and `createNodeFromSelection(qc, boardId, plugin, at)` helpers.
  - `PluginsPanel` — packs list (name + count, selected = white bg/600), plugin rows (mark tile with tint/ink, name, does, runs on, Add/Added toggle; "Not connected" tag when status not available), footer line + "Build a plugin" (opens `docs/plugins.md` on GitHub-less local: render as a link to `/docs/plugins` if served, else show the doc path text).
  - `NodesMenu` — list of added plugins; choosing one → `createNodeFromSelection` near the selection (or canvas centre).
  - `NodeCard` (HTML overlay positioned with `toScreenBounds`, keyboard reachable) — header (tile, name, runs on), input chips (thumbnail or "note", remove button `aria-label="Remove input ‹label›"`), settings (summary line; clicking opens inline param fields), output area (generated thumbnails from `output.created_item_ids`, `text`, `table`, or "‹runs_on› not connected"), progress bar + last progress text while queued/running, error text when failed, Run / Run again (disabled with reason from `canRun`), secondary button opens the settings, `⋯` with Remove node. Draggable by the header (moves via `patchNode`, undoable).
- [ ] **Step 1: Failing tests.** `nodeLogic.test.ts`: `summaryLine` for part/whole; `paramFields` honours `x-show-if`; `canRun` false for not_connected, below min, removed input. `PluginsPanel.test.tsx`: switching pack lists its plugins; Add calls `addBoardPlugin`, then shows Added; not-connected plugin shows the tag. `NodeCard.test.tsx`: Run calls `runNode`; running state shows progress and disables Run; failed shows the message and enables Run again; removing an input chip calls `patchNode` with the rest; placeholder plugin shows "not connected" and disabled Run; typing in a param field doesn't trigger tool shortcuts.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS; `npm test`; lint; tsc.
- [ ] **Step 5:** Commit `feat(plugins): plugins panel, nodes menu and node cards`.

---

### Task 13: End-to-end flows

**Files:**
- Create: `frontend/tests/e2e/round2.spec.ts`
- Modify: `frontend/tests/e2e/explore.spec.ts`, `demo-flow.spec.ts` (selectors moved by the new shell; keep their intent), README (screens section: calm board, notes, axis, plugins)

- [ ] **Step 1:** Write three tests with mock providers (follow `helpers.ts`): (a) note: press `N`, click canvas, type "Strap in waxed canvas, dark olive", `Esc`, hover, Visualize → a generated image appears with caption "generated"; (b) axis: select seeded image, Axis tool, pick an attribute, options appear as text cards, click one, Visualize, Regenerate → "take 2", Keep → card shows "· kept", reload → still kept, Un-keep → text card again; (c) plugins: open Plugins rail, Add "Palette & material", select an image, Nodes → Palette, Run → a note starting "Palette:" appears and the node shows done.
- [ ] **Step 2:** Run `make e2e` → new tests FAIL only for real bugs; fix in the owning code. Update the two existing specs for new selectors.
- [ ] **Step 3:** Run full `make e2e` (6/6), backend suite, frontend suite, lint.
- [ ] **Step 4:** Commit `test(e2e): notes, axis keep, and plugin node flows`.
