# Explore → Visualize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Text-first variation. Muse Spark proposes named options for one attribute of an image. The options show in the drawer under that attribute and as note cards on the canvas, kept in sync. Visualizing one option edits the source image through a swappable image provider, then checks the result.

**Architecture:** A new backend package `app/explore/` holds prompts, schemas, the service, visualize and the check. It persists to two new tables and exposes typed endpoints, so a later agent can call the same actions. Image editing goes through a new `ImageProvider` protocol (`muse-image` | `mock`). Visualize runs as a job, reuses ingest + `parse_item`, and publishes board events. On the frontend, a new `explore` drawer panel and a new konva note node read the same React Query cache, which board SSE events keep fresh.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic (SQLite), pydantic v2, openai SDK on httpx2 (Meta API is OpenAI-compatible), React 19 + TanStack Query, react-konva, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-explore-visualize-design.md` (read it first; "Decisions after the builder check" and "Two places, one list" are binding).

## Global Constraints

- Branch `feat/explore-visualize`. Existing suites must stay green: `make test` (558 backend), `cd frontend && npx vitest run` (109), `make lint`, `make e2e`.
- Tests never hit the network: providers are mock in tests (`tests/conftest.py` forces `REASONING_PROVIDER=mock` etc.). Add `IMAGE_PROVIDER=mock` to that autouse fixture.
- Settings: `IMAGE_PROVIDER` (code default `muse-image`, `.env.example` default `mock`), `IMAGE_MODEL` default `muse-image-1.0`, `EXPLORE_ENABLED` default `True`.
- Muse Image is called only on an explicit Visualize click. Never generate automatically.
- Generated items: `origin="generated"`, `rights_status="generated"`, caption "generated · <model id>". They must never be shown with a licence credit.
- Options: 6–10 per batch, `distance` ∈ `near|bold|wild`, names unique (case-insensitive) within an exploration.
- One exploration per (source item, attribute key). Shape-kind attributes cannot be explored.
- Edit prompt default: `Change only <attribute label> to <option name>: <description>. Keep everything else exactly the same.` (Spark may supply a better `edit_prompt`; use it when non-empty.)
- Copy: the toolbar button reads **Explore** (key `V`); the old Vary panel stays reachable through **Find real examples** and when `EXPLORE_ENABLED` is off.
- Follow existing style: `# fmt: skip` dict literals, repos in `app/db/repos/`, `AppError(status, CODE, message)`, `events.publish(board_id, type, data)`, `jobs.register` / `jobs.enqueue`.

## Review Focus

1. **Spark returns junk.** This covers duplicate names, names that repeat earlier options, fewer than 6 options, `value` that doesn't fit the kind, or unknown `keeps` keys. Expected: duplicates and repeats are dropped, bad values are coerced or the option is dropped, and unknown keeps are filtered. If nothing is left, return 502 `EXPLORE_EMPTY` with a readable message. Never store a broken option. (Task 4 tests.)
2. **The image call fails or times out.** Expected: no orphan item, the option goes back to `open` with `last_error` set, an `explore.updated` event fires, and the note and drawer show "Couldn't visualize, try again". (Task 5 tests.)
3. **Visualize is clicked twice while a visualize is still running.** Expected: the second POST returns 409 `VISUALIZE_IN_PROGRESS`, and only one image is created. (Task 5 test.)
4. **The source item is unparsed, or the attribute has no value.** Expected: explore still works (the prompt says the current value is unknown). Visualize still works. The check reports "kept n of m" only over attributes the source actually knows. (Tasks 4 and 5 tests.)
5. **The source item is removed while its options are on the canvas.** Expected: those notes and their lines disappear, and nothing crashes. `GET /explorations` excludes explorations whose source is removed. (Tasks 4 and 8 tests.)

---

### Task 1: Image provider

**Files:**
- Create: `backend/app/providers/image_gen.py`
- Modify: `backend/app/providers/__init__.py` (add `get_image_provider`), `backend/app/config.py`, `.env.example`, `backend/tests/conftest.py` (`IMAGE_PROVIDER=mock`), `backend/scripts/smoke_meta.py` (one edit call behind `--image`)
- Test: `backend/tests/unit/providers/test_image_gen.py`

**Interfaces:**
- Produces:
  - `class ImageProvider(Protocol): id: str; model: str; is_mock: bool; def edit(self, image: bytes, prompt: str) -> bytes`, which returns PNG bytes.
  - `class MuseImageProvider(client: openai.OpenAI, model: str, *, max_retries: int, timeout: float)`
  - `class MockImageProvider` (`id = "mock"`, `model = "mock-image"`, `is_mock = True`)
  - `get_image_provider(settings: Settings) -> ImageProvider`. It raises `ModelError("PROVIDER_MISCONFIGURED")` for an unknown name or a missing `MODEL_API_KEY`.

- [ ] **Step 1: Write failing tests.**
  - `test_mock_edit_is_deterministic_png`: the same input gives the same output, the output decodes with PIL, the size equals the input size, and the output differs from the input bytes.
  - `test_muse_image_posts_multipart_edit`: use `tests/unit/providers/fake_http.py` to route `POST {base}/images/edits` and return `{"data":[{"b64_json": <webp b64>}]}`. Assert the request is multipart, has `model=muse-image-1.0` and has a `prompt` field. Assert the result is PNG bytes (it starts with `b"\x89PNG"`).
  - `test_muse_image_shrinks_large_source`: a 4000×3000 source is sent with its long edge at most 1536.
  - `test_get_image_provider_unknown_raises`.
  - `test_get_image_provider_needs_key`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/providers/test_image_gen.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** `MuseImageProvider.edit` calls `client.images.edit(model=..., image=("source.png", png, "image/png"), prompt=...)` inside `call_model(...)` (same retry/timeout path as reasoning). It decodes `data[0].b64_json` and re-encodes it to PNG with PIL. Before sending, it shrinks the source with PIL to a long edge of at most 1536. `MockImageProvider` blends the source 20% towards a colour derived from `sha256(prompt)`.
- [ ] **Step 4: Run** the same command. Expected: PASS. Then run `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with message `feat(providers): swappable image edit provider (muse-image | mock)`.

### Task 2: Schema, migration, repo

**Files:**
- Modify: `backend/app/db/models.py`, `backend/app/db/ids.py` (`"exploration": "exp_"`, `"option": "opt_"`), `backend/app/api/schemas.py` (`item_to_dict` adds `explore_option_id`, `generation`, `check`)
- Create: `backend/alembic/versions/0006_explore.py`, `backend/app/db/repos/explore.py`
- Test: `backend/tests/unit/db/test_explore_repo.py`

**Interfaces:**
- Produces:
  - `ORIGINS` gains `"generated"` and `RIGHTS` gains `"generated"`.
  - `BoardItem` gains `explore_option_id: str | None` (FK to `explore_options.id`), `generation_json: Any` (`{"model", "prompt", "option_id"}`) and `check_json: Any`.
  - `class Exploration` (table `explorations`): `id`, `board_id`, `item_id` (FK board_items), `key`, `created_at`, with `UniqueConstraint(item_id, key)`.
  - `class ExploreOption` (table `explore_options`): `id`, `exploration_id`, `parent_option_id` (nullable self-FK), `batch` (int), `steer` (str | None), `name`, `description`, `distance`, `value_json`, `keeps_json` (list[str]), `edit_prompt`, `status` (`open|dismissed|visualizing|visualized`), `last_error` (str | None), `x` and `y` (float | None), `created_at`.
  - Repo `app/db/repos/explore.py`:
    - `get_or_create(session, board_id, item_id, key) -> Exploration`
    - `add_options(session, exploration_id, rows: list[dict]) -> list[ExploreOption]`
    - `options(session, exploration_id) -> list[ExploreOption]`
    - `get_option(session, option_id) -> ExploreOption | None`
    - `for_board(session, board_id) -> list[tuple[Exploration, list[ExploreOption]]]` (skips explorations whose source item is soft-deleted; skips dismissed options)
    - `update_option(session, option_id, **fields) -> ExploreOption | None`
    - `next_batch(session, exploration_id) -> int`
    - `option_to_dict(o) -> dict` and `exploration_to_dict(e, opts) -> dict`
- The check constraints on `board_items` change, so migration 0006 uses `op.batch_alter_table("board_items", recreate="always")` to swap `ck_item_origin` and `ck_item_rights` and to add the three columns. The licensed-iff-corpus constraint stays.

- [ ] **Step 1: Write failing tests.**
  - `test_get_or_create_is_unique_per_item_key`: two calls return the same id.
  - `test_for_board_skips_removed_source_and_dismissed`.
  - `test_generated_item_allowed`: create a `BoardItem(origin="generated", rights_status="generated", corpus_item_id=None)` and flush with no error.
  - `test_migration_upgrade_head`: alembic upgrade on a temp SQLite file creates both tables. Follow the existing pattern in `tests/unit/db/`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/db/test_explore_repo.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the models, migration, repo and `item_to_dict` fields.
- [ ] **Step 4: Run** the full backend suite with `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(db): explorations, explore options, generated items`.

### Task 3: Reasoning methods: explore_options and check_target

**Files:**
- Create: `backend/app/explore/__init__.py`, `backend/app/explore/schema.py`, `backend/app/explore/prompts.py`
- Modify: `backend/app/providers/reasoning.py` (protocol plus three providers)
- Test: `backend/tests/unit/explore/test_prompts_schema.py`, plus additions in `tests/unit/providers/test_mocks_and_factories.py`

**Interfaces:**
- Produces:
  - `OPTIONS_SCHEMA: dict` (strict JSON schema). It is `{"options": [{"name", "description", "distance": enum[near,bold,wild], "value": string, "keeps": [string], "edit_prompt": string}]}`. `value` is always a string in the schema and is coerced per kind in Task 4.
  - `CHECK_SCHEMA: dict` is `{"answer": enum[yes,no,unclear], "confidence": number, "box": [4 numbers 0..1] | null, "note": string}`.
  - `build_explore_prompt(*, spec: AttributeSpec, current: Value, attributes: list[AttributeRecord], board_title: str, board_context: str, existing_names: list[str], parent: dict | None, steer: str | None, mode: Literal["initial","more","further"]) -> str`
  - `build_check_prompt(*, label: str, option_name: str, description: str) -> str`
  - New `ReasoningProvider` methods:
    - `explore_options(self, images: list[bytes], prompt: str) -> dict`, which uses `OPTIONS_SCHEMA` (effort `low` on Spark 1.3).
    - `check_target(self, images: list[bytes], prompt: str) -> dict`, which uses `CHECK_SCHEMA`.
  - Spark 1.3 uses `_run(...)`. Spark Open uses `_run(...)`. The mock returns 8 fixed watch-agnostic options (`"Option A"` … `"Option H"`, distances cycling near/bold/wild, `value` `"option_a"`…, keeps `[]`). With a `truth`, it returns `{"answer":"yes","confidence":0.9}` for check.

- [ ] **Step 1: Write failing tests.**
  - `test_prompt_names_attribute_current_and_board`: the prompt contains the label, the current value and the board title.
  - `test_prompt_lists_existing_names_to_avoid` (mode `more`).
  - `test_prompt_further_asks_bolder`.
  - `test_prompt_branch_mentions_parent`.
  - `test_prompt_vocabulary_is_inspiration_not_limit`: for a closed enum, the prompt says options may go beyond the listed values.
  - `test_unknown_current_value_is_stated`.
  - `test_options_schema_is_strict` (`additionalProperties: false` everywhere, all keys required).
  - `test_mock_explore_options_shape` and `test_mock_check_target_shape`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/explore -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** The prompt must ask for specific, nameable design moves grounded in this image and board, not a list of vocabulary values (spec anti-goal). The `keeps` keys must come from the given attribute keys.
- [ ] **Step 4: Run** the full backend suite. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(explore): option and check prompts, provider methods`.

### Task 4: Explore service and API

**Files:**
- Create: `backend/app/explore/service.py`, `backend/app/api/explore.py`
- Modify: `backend/app/main.py` (router), `backend/app/demo.py` only if explore must be listed (it must **not** be open in demo mode: leave it locked)
- Test: `backend/tests/unit/explore/test_coerce.py`, `backend/tests/integration/api/test_explore.py`

**Interfaces:**
- Consumes: Task 2 repo, Task 3 methods, `extraction.service.current_lens`, `orchestrator.source_records`, `extraction.service._image_for` (use the full original image), `get_reasoning`.
- Produces:
  - `coerce_option_value(spec: AttributeSpec, raw: str, *, current: Value) -> Value | None`. For enum and text it returns `canonical_token(raw)`, ignoring closed vocab. For number it returns a float within the spec's min/max (else None). For color it returns the lowercased name. For ordinal it returns the value only if it's a scale step. For boolean it returns `not current` (None when current is unknown). Shape returns None.
  - `explore(session, item_id: str, key: str, *, steer: str | None, parent_option_id: str | None, mode: Literal["initial","more","further"]) -> tuple[Exploration, list[ExploreOption]]`. It cleans, dedupes (case-insensitive across the exploration), filters keeps to known keys, stores the new batch and publishes `explore.updated` with `exploration_to_dict`.
  - `ExploreBody(BaseModel)`: `key: str; steer: str | None = Field(None, max_length=200); parent_option_id: str | None = None; mode: Literal[...] = "initial"`.
  - Routes (prefix `/api`):
    - `POST /items/{item_id}/explore` with `ExploreBody` → 200 `exploration_to_dict`.
    - `GET /boards/{board_id}/explorations` → `{"explorations": [...]}`.
    - `PATCH /options/{option_id}` with `{status?: "dismissed"|"open", x?: float, y?: float}` → option dict, and publishes `explore.updated`.
  - Errors:
    - 404 `ITEM_NOT_FOUND` / `OPTION_NOT_FOUND`
    - 400 `ATTRIBUTE_NOT_IN_LENS`
    - 400 `KIND_NOT_EXPLORABLE` (shape)
    - 409 `LENS_REQUIRED` (board has no lens)
    - 502 `EXPLORE_EMPTY`
    - 503 `FEATURE_OFF` when `EXPLORE_ENABLED` is false
  - Synchronous call. Measure live latency once with `make smoke`-style manual run. If p50 > 30 s, note it in the commit and open a follow-up; do not build a job now.

- [ ] **Step 1: Write failing tests.**
  - Coerce, one test per kind: an enum outside its vocab is kept as a token, a number outside its range gives None, ordinal off-scale gives None, boolean flips, shape gives None.
  - API tests, using a board with a curated `watch` lens and a mock reasoning `truth` that returns duplicate and repeat names:
    - `test_explore_creates_options_on_first_call` (6–10).
    - `test_more_appends_without_repeats`.
    - `test_steer_stored_per_batch`.
    - `test_branch_sets_parent`.
    - `test_same_item_key_reuses_exploration`.
    - `test_unparsed_item_still_explores`.
    - `test_all_junk_returns_502_explore_empty`.
    - `test_unknown_key_400`.
    - `test_shape_kind_400`.
    - `test_dismiss_hides_from_board_list`.
    - `test_removed_source_hides_exploration`.
    - `test_patch_saves_position`.
    - `test_feature_off_503`.
    - `test_demo_mode_locks_explore` (POST without unlock → the existing demo 403 code).
    - `test_explore_publishes_event`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/explore tests/integration/api/test_explore.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the service and router.
- [ ] **Step 4: Run** the full backend suite and `uv run ruff check . && uv run mypy app scripts`. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(explore): explore service and endpoints`.

### Task 5: Visualize job, vocabulary update, check

**Files:**
- Create: `backend/app/explore/visualize.py`, `backend/app/explore/check.py`, `backend/app/explore/vocab.py`
- Modify: `backend/app/api/explore.py` (add the route)
- Test: `backend/tests/integration/api/test_visualize.py`, `backend/tests/unit/explore/test_vocab_check.py`

**Interfaces:**
- Consumes:
  - Task 1 `get_image_provider`.
  - Task 2 repo and columns.
  - Task 3 `check_target`.
  - `ingest.images.decode_image`, `storage.files.save_original` and `save_thumb`, `ingest.common.create_item`.
  - `extraction.service.parse_item(session, item_id)` (sync).
  - `validation.comparators.compare` + `AttrValue.from_record` + `retrieval.config.RANKING_CONFIG`.
  - `orchestrator.source_records`.
  - `lenses_repo.save`.
- Produces:
  - `add_vocabulary(session, board_id: str, key: str, value: Value) -> bool`. For a closed enum whose vocab lacks the value, it saves a new confirmed lens version (origin `"edited"`, same domain) with the token appended, sets `board.lens_id`, and returns True. Otherwise it returns False. Open vocab and non-enum kinds are a no-op.
  - `check_generated(session, source_id: str, generated_id: str, option: ExploreOption) -> dict`. It returns `{"target": {"answer", "confidence", "box", "note"}, "kept": int, "of": int, "drifted": [keys]}`. Only `keeps` keys whose source value is reliable are counted, and `"unknown"` comparator verdicts count as neither kept nor drifted.
  - `request_visualize(session, option_id: str) -> None`. It raises 409 `VISUALIZE_IN_PROGRESS` if the status is `visualizing`, sets `visualizing`, publishes, and enqueues job `"visualize_option"`.
  - `visualize_job(option_id: str) -> None`. In order:
    1. Edit the image.
    2. Ingest it as a new item: `origin="generated"`, `rights_status="generated"`, `parent_item_id=source`, `explore_option_id`, `generation_json`. Place it to the right of the option's note (`x = (option.x or source.x + source.w + 40) + 260`).
    3. Publish `item.added`.
    4. Call `add_vocabulary`.
    5. Run `parse_item`.
    6. Run `check_generated`, store `check_json`, and publish `item.updated`.
    7. Set the option to `visualized` and publish `explore.updated`.
    - On any `ModelError` or `AppError` in steps 1–2: set the option back to `open` with `last_error=<code>`, publish, and create no item. A failure in steps 5–6 keeps the item and stores `check_json={"error": code}`.
  - Route: `POST /api/options/{option_id}/visualize` → 202 `{"option_id": ..., "status": "visualizing"}`. Locked in demo mode unless unlocked.

- [ ] **Step 1: Write failing tests**, using `jobs` run inline as existing run tests do (see `tests/runs_world.py`).
  - `test_visualize_creates_generated_item_with_lineage`
  - `test_generated_item_dict_has_generation_and_no_licence`
  - `test_second_visualize_while_running_409`
  - `test_revisualize_after_done_creates_second_item`
  - `test_image_failure_resets_option_no_item` (patch the provider to raise `ModelError("MODEL_UNAVAILABLE")`)
  - `test_closed_enum_value_added_to_lens_vocab`
  - `test_open_vocab_unchanged`
  - `test_check_counts_only_reliable_keeps`
  - `test_check_target_answer_stored`
  - `test_parse_failure_keeps_item_with_check_error`
- [ ] **Step 2: Run** `uv run pytest tests/integration/api/test_visualize.py tests/unit/explore -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full backend suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(explore): visualize an option, grow the vocabulary, check the result`.

### Task 6: Frontend data layer

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/queries.ts`, `frontend/src/events.ts`, `backend/app/api/demo.py` (`GET /api/demo/status` adds `"explore_enabled": bool`), `frontend/src/demo.ts`
- Create: `frontend/src/explore/hover.ts`
- Test: `frontend/src/events.test.ts` (add cases), `frontend/src/explore/hover.test.ts`

**Interfaces:**
- Produces (TS):
  - `type Distance = 'near' | 'bold' | 'wild'`
  - `interface ExploreOption { id; exploration_id; parent_option_id: string | null; batch: number; steer: string | null; name; description; distance: Distance; value: string | number | boolean | null; keeps: string[]; status: 'open' | 'dismissed' | 'visualizing' | 'visualized'; last_error: string | null; x: number | null; y: number | null }`
  - `interface Exploration { id; board_id; item_id; key; options: ExploreOption[] }`
  - `Item` gains `explore_option_id: string | null`, `generation: { model: string; prompt: string; option_id: string } | null` and `check: GeneratedCheck | null`. `rights_status` adds `'generated'`.
  - `interface GeneratedCheck { target?: { answer: 'yes' | 'no' | 'unclear'; confidence: number; note: string }; kept?: number; of?: number; drifted?: string[]; error?: string }`
  - API functions:
    - `exploreItem(itemId, body: { key: string; steer?: string; parent_option_id?: string; mode?: 'initial' | 'more' | 'further' }): Promise<Exploration>`
    - `listExplorations(boardId): Promise<Exploration[]>`
    - `patchOption(optionId, body: { status?: 'dismissed' | 'open'; x?: number; y?: number }): Promise<ExploreOption>`
    - `visualizeOption(optionId): Promise<void>`
  - `keys.explorations(boardId)`
  - `useExplorations(boardId)`
  - `EVENT_TYPES` adds `'explore.updated'`. `applyEvent` upserts the exploration into `keys.explorations` (it replaces by id, and the server sends the full exploration).
  - `hover.ts` is a tiny external store: `useHoveredOption(): string | null` and `setHoveredOption(id: string | null)`, written in the same style as `canvas/selection.ts`.
  - `useDemo()` exposes `exploreEnabled: boolean`.

- [ ] **Step 1: Write failing tests**: `applyEvent explore.updated upserts exploration`, `explore.updated for another board ignored`, and `hover store notifies subscribers`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/events.test.ts src/explore`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run && npx tsc -b && npm run lint`. Expected: PASS. Also run backend `uv run pytest tests/integration/api/test_demo.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(frontend): explore data layer, events, hover store`.

### Task 7: Explore drawer panel ("in the dimension")

**Files:**
- Create: `frontend/src/panels/ExplorePanel.tsx`, `frontend/src/explore/logic.ts`
- Modify: `frontend/src/panels/registerPanels.ts` (register `'explore'`), `frontend/src/canvas/ItemToolbar.tsx` (the label is **Explore** and it opens `'explore'` when `exploreEnabled`, otherwise `'vary'`), `frontend/src/canvas/Canvas.tsx` (`onVary` → `onExplore`), `frontend/src/pages/BoardPage.tsx` (the `V` key follows the same rule), `frontend/src/index.css`
- Test: `frontend/src/panels/ExplorePanel.test.tsx`, `frontend/src/explore/logic.test.ts`

**Interfaces:**
- Consumes: Task 6 API and hooks, `useAttributes(itemId)` (lens attributes and records), `hover.ts`, the existing `startRun` in `vary/startRun.ts`, and the drawer `params`.
- Produces:
  - `optionTree(options: ExploreOption[]): Array<{ option: ExploreOption; depth: number }>`. It orders by batch, then creation, with children right after their parent and dismissed options removed.
  - `canFindReal(spec: AttributeSpec, value: ExploreOption['value']): boolean`. It returns true when `value` is non-null and (the enum is open, or its vocab includes the value, or the kind is not enum).
  - `findRealRequest(itemId: string, key: string, option: ExploreOption): VariationRequest`. It uses `mode: 'prefer'`, `target_values: [String(value)]`, `protected_keys: option.keeps` and `nudge: null`.
  - Drawer params: `{ key?: string; optionId?: string }` (canvas notes open the panel focused on a key and option).
- Behaviour:
  - The attribute list matches today's Vary step 1 (excluding shape).
  - Clicking an attribute expands it. If an exploration exists for it, its options show. Otherwise a steer input and an **Explore** button show.
  - Each option row shows the name, a distance tag, the description, and actions: **Visualize**, **Branch**, **Find real examples** (disabled with a hint when `!canFindReal`), **Dismiss**.
  - **Find real examples** calls `startRun` with `findRealRequest` and then opens the existing `'vary'` panel's run view the same way `VaryPanel` does after Run.
  - Rows in `visualizing` show a spinner. A non-null `last_error` shows "Couldn't visualize, try again."
  - At the bottom of the list there are **More**, **Further** and a steer input.
  - Hovering a row calls `setHoveredOption(id)`, and a row whose id equals `useHoveredOption()` is highlighted.
  - API errors are shown inline by `message`.

- [ ] **Step 1: Write failing tests.**
  - logic: `optionTree nests branches`, `optionTree drops dismissed`, `canFindReal closed enum outside vocab false`, `canFindReal after vocab update true`, `findRealRequest maps keeps`.
  - panel, using MSW or the fetch-mock pattern already used in `VaryPanel.test.tsx`: `explore button calls exploreItem with steer`, `more sends mode more`, `branch sends parent_option_id`, `visualize calls visualizeOption and shows spinner from status`, `dismiss patches status`, `error message shown on 502`, `hover sets hovered option`, `params.key opens that attribute expanded`.
- [ ] **Step 2: Run** `npx vitest run src/panels/ExplorePanel.test.tsx src/explore`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run && npx tsc -b && npm run lint`. Expected: PASS (update the `ItemToolbar` test for the label).
- [ ] **Step 5: Commit** with message `feat(frontend): explore panel, options listed under the dimension`.

### Task 8: Option notes on the canvas

**Files:**
- Create: `frontend/src/canvas/OptionNote.tsx`, `frontend/src/canvas/notes.ts`
- Modify: `frontend/src/canvas/Canvas.tsx` (render notes plus lines, and include generated-item lines from note to item), `frontend/src/canvas/palette.ts` (note colours)
- Test: `frontend/src/canvas/notes.test.ts`, `frontend/src/canvas/OptionNote.test.tsx`

**Interfaces:**
- Consumes: `useExplorations`, `patchOption`, `hover.ts`, `lineagePoints` and `itemBounds` from `nodeProps.ts`, and `onOpenPanel('explore', itemId, { key, optionId })`.
- Produces:
  - `NOTE_W = 220` and `NOTE_H = 96`.
  - `fanPositions(source: Bounds, count: number, start: number): Array<{ x: number; y: number }>`. It produces a column to the right of the source at `source.x + source.w + 60`, vertically centred on the source, with a 16 px gap. When there are more than 6 notes, it wraps into a second column 240 px further right. `start` continues numbering for later batches.
  - `notePlacement(option: ExploreOption, index: number, source: Bounds): { x: number; y: number }`. It uses the saved `x`/`y` when present, otherwise `fanPositions`.
  - `noteLines(explorations, items): Array<{ id; points: number[] }>`. It draws a source→note line for each option (parent option→note for branches) and a note→generated-item line for items whose `explore_option_id` matches.
- Behaviour:
  - A note shows its name, a distance tag and a description clamped to 2 lines.
  - Notes are draggable, and drag end calls `patchOption({x, y})`.
  - Clicking a note opens the explore panel focused on its key and option.
  - Hovering a note sets the hovered option. The note matching the hovered id draws an accent outline.
  - Notes for a removed source are not rendered.
  - Lines are always visible for notes. Item lineage stays selection-only as today.

- [ ] **Step 1: Write failing tests.**
  - `fanPositions column right of source`, `fanPositions wraps after 6`, `notePlacement prefers saved position`, `noteLines branch connects to parent`, `noteLines links generated item`, `noteLines skips removed source`.
  - Using the existing konva test setup in `ItemNode.test.tsx`: `OptionNote renders name and distance`, `drag end patches position`, `hovered note outlined`.
- [ ] **Step 2: Run** `npx vitest run src/canvas/notes.test.ts src/canvas/OptionNote.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run && npx tsc -b && npm run lint`. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(canvas): explore options as notes linked to the source`.

### Task 9: Generated item caption and check verdict

**Files:**
- Modify: `frontend/src/canvas/CreditCaption.tsx`, `frontend/src/canvas/credit.ts`, `frontend/src/canvas/ItemNode.tsx` (or `ItemDecorations` in `Canvas.tsx`, wherever the status dot lives), `frontend/src/panels/InspectPanel.tsx` (a "Generated from <option name>" line with the check)
- Create: `frontend/src/explore/verdict.ts`
- Test: `frontend/src/explore/verdict.test.ts`, `frontend/src/canvas/CreditCaption.test.tsx` (add cases)

**Interfaces:**
- Produces: `verdictText(check: GeneratedCheck | null, label: string, optionName: string): { text: string; tone: 'ok' | 'warn' | 'pending' | 'error' }`. These cases are pinned:
  - `null` → `{ "Checking…", pending }`
  - target yes → `"<label> → <optionName> ✓ · <kept> of <of> kept"` with `ok` when `drifted` is empty, otherwise `warn` with `" · drifted: <labels>"`
  - target no → `"<label> didn't change to <optionName>"` with `warn`
  - target unclear → `"<label>: unclear"` with `warn`
  - `error` → `"Check failed"` with `error`
- Caption: generated items show `generated · <generation.model>` and never the licence credit.

- [ ] **Step 1: Write failing tests** for each `verdictText` case and `caption for generated item shows model, no licence`.
- [ ] **Step 2: Run** `npx vitest run src/explore/verdict.test.ts src/canvas/CreditCaption.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run && npx tsc -b && npm run lint`. Expected: PASS.
- [ ] **Step 5: Commit** with message `feat(frontend): generated caption and check verdict`.

### Task 10: End-to-end path, docs, live smoke

**Files:**
- Create: `frontend/tests/e2e/explore.spec.ts`
- Modify: `backend/scripts/e2e_prepare.py` (`IMAGE_PROVIDER=mock` in the e2e env if it sets providers), `README.md` (an Explore section, the image provider setting, and the India/Muse Image note: "dev only; swap `IMAGE_PROVIDER` for the demo"), `.env.example`

- [ ] **Step 1: Write the e2e test** `explore option then visualize`, using the existing `helpers.ts` (a seeded board with mock providers):
  1. Select the first item and press `V`.
  2. Click attribute `Markers` (or the first enum attribute in the mock lens), then **Explore**.
  3. Expect ≥ 6 rows in the drawer and the same number of notes on the canvas. Check via the `data-testid="option-note"` count in an accessibility mirror if konva nodes aren't queryable. Use the same approach `demo-flow.spec.ts` uses for canvas items.
  4. Click **Visualize** on the first row, and expect a new item with the caption `generated · mock-image` within 10 s.
  5. Expect the verdict text to appear.
- [ ] **Step 2: Run** `make e2e`. Expected: the new spec fails until wiring gaps are fixed, then everything passes.
- [ ] **Step 3: Live smoke (manual, user's `.env`).**
  - Run `make dev`. Open the watch board and explore Markers on the Guinand photo. Record the explore latency.
  - Visualize "Devanagari numerals" once. Confirm the image, caption and verdict.
  - Note both in the commit message body.
- [ ] **Step 4: Run** every suite: `make test`, `cd frontend && npx vitest run`, `make lint` and `make e2e`. Expected: all pass. Report the counts.
- [ ] **Step 5: Commit** with message `test(e2e): explore and visualize; docs`.

---

## Self-review notes

- Spec coverage:
  - Goals 1–6 map to Tasks 3–5 (options, more/further/steer/branch, visualize, check, find real) and Tasks 7–9 (both places in sync, caption, verdict).
  - Decisions map as follows: vocab (T5), direct check (T3/T5), all kinds (T4 coerce), one exploration per item+key (T2/T4), provider on the protocol (T3), re-visualize (T5).
  - The feature flag is covered by T4 and T6/T7. Demo lock is in T4/T5. Non-goals are not touched.
- Type names are used consistently across tasks: `ExploreOption`, `Exploration`, `GeneratedCheck`, `explore.updated`, `explore_option_id`, `generation_json`/`generation`, `check_json`/`check`.
