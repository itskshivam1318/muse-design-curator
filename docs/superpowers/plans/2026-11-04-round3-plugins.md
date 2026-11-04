# Round 3 Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Variation · Color (`recolor`), Clean-up, 3D (`mesh`) and Animate (`video`) as plugins that make options, plus the shared groundwork (knob widgets, masks for python plugins, option grid, fal long jobs, video / 3D outputs and viewers, caps).

**Architecture:** Everything stays inside round 2's single plugin engine (`backend/app/plugins/`). Python plugins get masks prepared by the host and may return up to 24 images, laid out as an option grid. Model plugins on fal are split into submit → poll → fetch with the fal request id persisted on the run so restarts resume instead of resubmitting. The node card renders `x-widget` hints; the board renders option outlines, inline video and a lazy 3D viewer.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic (SQLite), numpy + Pillow, httpx (fal queue REST API), pytest, uv; React 19, react-konva, @tanstack/react-query, vitest, Playwright, `@google/model-viewer` (lazy).

**Spec:** `docs/superpowers/specs/2026-11-02-round3-plugins-design.md`

## Global Constraints

- Worktree `/Users/shivam/Desktop/muse-round3`, branch `feat/round3-plugins`. Never merge, push or deploy without the owner's choice.
- Plugin ids: `recolor` (display name "Variation"), `cleanup`, `mesh`, `video`. Do not reuse the name `variation` in code (collides with `VariationRun`).
- Variation makes zero model calls once masks exist. Python plugins never receive `FAL_KEY` / `MODEL_API_KEY`; the env stays `PATH`, `HOME`, `PYTHONHASHSEED`.
- Recolor count 1–24, default 8. Python runner cap 24 images per run; model runner keeps 8 (`MAX_IMAGE_RESULTS`).
- GLB cap 50 MB; video uses the existing video ingest cap.
- New settings, defaults: `FAL_KEY: str | None = None`, `FAL_TIMEOUT_S: int = 600`, `FAL_POLL_S: float = 3.0`, `MESH_PER_BOARD_PER_DAY: int = 10`, `VIDEO_PER_BOARD_PER_DAY: int = 10`, endpoint overrides `FAL_MESH_FAST`, `FAL_MESH_DETAILED`, `FAL_VIDEO_STANDARD`, `FAL_VIDEO_PRO` (str, defaults = the verified fal endpoint ids).
- Caps: `limits.check_and_count(board_id, kind)` before every paid step, `limits.refund` on any failure that left the person with nothing. Kinds: `"mesh"`, `"video"` (new), Describe → `"render"`, first-time SAM for plugin masks → `"analyse"`. Never auto-retry a paid submit.
- Demo mode: unchanged guard (passcode unlock); user plugins never load in `DEMO_MODE`.
- A plugin whose `requires` setting is unset is "not connected"; `mesh` and `video` require `FAL_KEY`.
- Every new manifest has a plain `description` and a params schema the agent's `run_plugin` can fill without widgets.
- Placement uses `analysis/extract.free_slot` so nothing overlaps on the living board.
- Run `make lint` (oxlint, `tsc -b`, ruff) and the full suites before each task's commit; e2e (`make e2e`) at the end.

## Review Focus

1. An item with zero or one mask part wired to Variation → a clear "needs at least two parts" failure, no crash, no paid call. (Task 5)
2. A fal job in flight when the server restarts → the run resumes polling the stored request id; no second submit, no second cap slot. (Task 7)
3. An Animate End frame that was deleted, is a note, or is on another board → `PLUGIN_BAD_INPUT` before any paid call, slot refunded. (Task 9)
4. Clear after the person moved or kept some options → only still-flagged options of that run are removed; undo restores them. (Task 3)
5. SAM finds nothing for the object mask → falls back to the union of the item's part masks; if none, `REGION_EMPTY` reported on the node, analyse slot refunded. (Task 2)

---

### Task 1: Foundation — schema, settings, manifest, limits

**Files:**
- Create: `backend/alembic/versions/0013_round3_plugins.py` (down_revision `0012_board_chat`)
- Modify: `backend/app/db/models.py` (ITEM_KINDS, BoardItem, PluginRun), `backend/app/config.py`, `backend/app/plugins/manifest.py`, `backend/app/plugins/runners.py` (OUTPUT_KINDS, caps), `backend/app/plugins/registry.py` (NOT_CONNECTED_MODELS), `backend/app/analysis/limits.py`, `backend/app/api/schemas.py` (item_to_dict), `frontend/src/api.ts` (Item, ItemKind, PluginInfo)
- Test: `backend/tests/unit/plugins/test_manifest.py`, `backend/tests/unit/analysis/test_limits.py`, `backend/tests/integration/db/test_migrations.py` (existing pattern)

**Interfaces:**
- Produces:
  - `ITEM_KINDS = ("image", "video", "link", "note", "model")`
  - `BoardItem.option_run_id: Mapped[str | None]` (indexed; null = not an option)
  - `PluginRun.external_json: Mapped[Any]` — `{"endpoint": str, "request_id": str, "status": str, "cap": str}` while a fal job is in flight
  - `Manifest.needs: list[Literal["parts", "object_mask"]] = []`
  - `Output` / `OUTPUT_KINDS` gain `"video"`, `"model3d"`
  - `MAX_IMAGE_RESULTS = 8` (model), `MAX_PYTHON_IMAGES = 24`
  - `limits.Kind = Literal["analyse", "render", "mesh", "video"]`
  - `item_to_dict` includes `option_run_id`; TS `Item.option_run_id: string | null`, `ItemKind` adds `'model'`
  - `registry.NOT_CONNECTED_MODELS` becomes empty; status driven by `requires`

- [ ] **Step 1: Write failing tests**
  - `test_manifest_accepts_needs_and_new_outputs`: a manifest with `"needs": ["parts"]`, `"outputs": ["images", "model3d"]` validates; `"needs": ["bogus"]` raises.
  - `test_limits_mesh_and_video_kinds`: with `MESH_PER_BOARD_PER_DAY=2`, two `check_and_count(b, "mesh")` pass, the third raises `AppError` 429 `DAILY_LIMIT`; `refund` frees one slot; `"video"` uses `VIDEO_PER_BOARD_PER_DAY`.
  - `test_migration_0013_round_trip`: upgrade adds `board_items.option_run_id`, `plugin_runs.external_json`, accepts kind `"model"`; downgrade removes them.
- [ ] **Step 2: Run them, expect FAIL** — `cd backend && uv run pytest tests/unit/plugins/test_manifest.py tests/unit/analysis/test_limits.py tests/integration/db -q`
- [ ] **Step 3: Implement** the fields above. Migration uses the repo's `migration_transaction` / batch pattern from `0007_round2.py` for the kind CHECK constraint.
- [ ] **Step 4: Run tests, expect PASS**; run the full backend suite (placeholders `mesh` / `video` now report not connected via `requires`, so update their manifests' `requires` to `["FAL_KEY"]` here).
- [ ] **Step 5: Commit** `feat(plugins): round 3 foundation — model item kind, option flag, fal run state, new caps`

### Task 2: Masks for python plugins (host side)

**Files:**
- Modify: `backend/app/analysis/locate.py`, `backend/app/plugins/runners.py` (`RunInput`, `_run_python` payload), `backend/app/plugins/service.py` (`_inputs`)
- Create: `backend/app/plugins/masks.py`
- Test: `backend/tests/integration/test_locate.py`, `backend/tests/integration/plugins/test_masks.py`

**Interfaces:**
- Consumes: `locate`, `PartMask` cache, `limits` (Task 1), `Manifest.needs`.
- Produces:
  - `locate_object(session, item_id) -> Region` — SAM prompted with the item's analysis summary truncated to `MAX_PROMPT_WORDS`, cached in `part_masks` under prompt `"object:" + <that text>`; falls back to the union of the item's located mask parts; raises 422 `REGION_EMPTY` if neither exists.
  - `prepare_masks(session, board_id, item, needs) -> PreparedMasks` where `PreparedMasks = {"parts": list[tuple[key, label, mask: np.ndarray]], "object": np.ndarray | None}`; takes one `"analyse"` slot only if at least one SAM call is needed, refunds it on error.
  - `RunInput` gains `parts: list[tuple[str, str, bytes]] | None` and `object_mask: bytes | None` (PNG bytes); `_run_python` writes them read-only to `in/<input>-part-<key>.png` / `in/<input>-object.png` and adds `"parts": [{"key","label","mask_path"}]`, `"object_mask_path"` to that input's payload.

- [ ] **Step 1: Write failing tests**
  - `test_locate_object_uses_cache`: second call makes no segmentation call (mock provider call count stays 1).
  - `test_locate_object_falls_back_to_part_union`: mock SAM returns not found; result mask == union of two part masks.
  - `test_locate_object_empty_raises`: no parts, SAM not found → `AppError` 422 `REGION_EMPTY`.
  - `test_prepare_masks_counts_once_and_refunds`: first call with two unlocated parts takes exactly one `"analyse"` slot; a failing SAM refunds it; a fully cached second call takes none.
  - `test_python_payload_has_mask_paths`: a test plugin with `needs: ["parts","object_mask"]` echoes its payload; each mask path exists, is read-only, and lies inside the run folder.
- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/integration/test_locate.py tests/integration/plugins/test_masks.py -q`
- [ ] **Step 3: Implement** as above; `_inputs` calls `prepare_masks` only when the manifest declares `needs`.
- [ ] **Step 4: Run, expect PASS**; full backend suite.
- [ ] **Step 5: Commit** `feat(plugins): host-prepared part and object masks for python plugins`

### Task 3: Option grid writeback, Keep and Clear

**Files:**
- Modify: `backend/app/plugins/writeback.py`, `backend/app/api/plugins.py`, `backend/app/api/items.py`
- Test: `backend/tests/unit/plugins/test_grid.py`, `backend/tests/integration/api/test_options_api.py`

**Interfaces:**
- Consumes: `BoardItem.option_run_id` (Task 1), `free_slot`.
- Produces:
  - `grid_cells(n: int, cell: tuple[float, float], cols: int = 4, gap: float = 24) -> list[tuple[float, float]]` (offsets from the grid's top-left, row-major).
  - `apply_output`: when a run creates more than one image, place them with `grid_cells` at a block position from `free_slot(session, board, node_bounds, block_size)` and set `option_run_id = run.id` on each; a single image keeps today's column placement and no flag. `output_json` gains `"option_item_ids"`.
  - `POST /api/items/{id}/keep-option` → item dict with `option_run_id = null`; 404 if not an option.
  - `POST /api/nodes/{id}/clear-options` → `{"removed_item_ids": [...]}`: soft-removes (the same path as `DELETE /items/{id}`) every item whose `option_run_id` is one of that node's runs; publishes `item.removed` per item so client undo can restore them.
  - Python runner enforces `MAX_PYTHON_IMAGES` (`PLUGIN_BAD_OUTPUT` above it).

- [ ] **Step 1: Write failing tests**
  - `test_grid_cells_four_wide`: `grid_cells(6, (100, 80))` == `[(0,0),(124,0),(248,0),(372,0),(0,104),(124,104)]`.
  - `test_batch_outputs_are_options_in_grid`: a 6-image result → 6 items with `option_run_id == run.id`, no two overlapping, none overlapping an existing item.
  - `test_single_output_not_option`: 1 image → `option_run_id is None`.
  - `test_keep_option_clears_flag`, `test_keep_non_option_404`.
  - `test_clear_options_removes_only_flagged`: keep 2 of 6, clear → 4 removed, the 2 kept remain; options from another node's run untouched.
  - `test_python_25_images_rejected`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS**; full backend suite.
- [ ] **Step 5: Commit** `feat(plugins): option grid for batch outputs; keep and clear options`

### Task 4: Shared cut-out and the Clean-up plugin

**Files:**
- Create: `backend/app/plugins/builtin/cleanup/cutout.py`, `backend/app/plugins/builtin/cleanup/main.py`
- Modify: `backend/app/plugins/builtin/cleanup/plugin.json`, `backend/app/analysis/extract.py` (`_crop` uses `cutout`), `backend/app/plugins/registry.py` (add `load_builtin_module`)
- Test: `backend/tests/unit/plugins/test_cutout.py`, `backend/tests/integration/plugins/test_cleanup_plugin.py`, existing `tests/integration/test_extract.py` stays green

**Interfaces:**
- Consumes: `needs: ["object_mask"]` (Task 2).
- Produces:
  - `cutout(image: PIL.Image.Image, mask: np.ndarray | None, box: tuple[int,int,int,int] | None, background: Literal["transparent","white"] = "transparent", margin: float = 0.0) -> PIL.Image.Image` — pure numpy / Pillow, no `app` imports (the shim imports it in isolation).
  - `registry.load_builtin_module(plugin_id: str, module: str) -> ModuleType` — host-side import of a built-in plugin's module by file path (used by `extract` and Task 8).
  - Manifest: runner `python`, entry `main.py`, `needs: ["object_mask"]`, inputs image 1–4, params `{background: enum [transparent, white] default transparent}`, outputs `["images"]`, `requires: []`, margin 0.04 of the bbox.

- [ ] **Step 1: Write failing tests**
  - `test_cutout_transparent_outside_mask`: alpha 0 outside, 255 inside; output size == mask bbox + 4% margin clamped to the image.
  - `test_cutout_white_background`: outside pixels == (255,255,255), mode RGB.
  - `test_cutout_empty_mask_raises_valueerror`.
  - `test_cleanup_plugin_makes_one_image_per_input` (mock SAM): two inputs → two images, no model calls besides segmentation.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**; `extract._crop` keeps its PNG metadata and semantics but delegates the pixel work to `cutout`.
- [ ] **Step 4: Run, expect PASS** (including `test_extract.py`).
- [ ] **Step 5: Commit** `feat(plugins): connect Clean-up; share the cut-out with extract`

### Task 5: Variation · Color (`recolor`)

**Files:**
- Create: `backend/app/plugins/builtin/recolor/{plugin.json,main.py,recolor.py}`
- Modify: `backend/app/plugins/packs.json` (add `recolor` to product, fashion, interior, auto)
- Test: `backend/tests/unit/plugins/test_recolor.py`, `backend/tests/integration/plugins/test_recolor_plugin.py`

**Interfaces:**
- Consumes: `needs: ["parts"]` (Task 2), option grid (Task 3).
- Produces (all pure numpy, in `recolor.py`):
  - `label_map(masks: list[np.ndarray]) -> np.ndarray` — int map, -1 = no part; a pixel goes to the smallest-area mask covering it.
  - `adjacency(labels: np.ndarray, n: int, dilate_px: int = 3) -> set[tuple[int, int]]`
  - `assignments(n_parts: int, n_colors: int, touching: set[tuple[int,int]], count: int, seed: int) -> list[tuple[int, ...]]` — distinct, deterministic for a seed; no touching pair shares a colour when `n_colors` allows, else fewest touching repeats first.
  - `recolor(rgb: np.ndarray, labels: np.ndarray, colors: dict[int, str], feather_px: int = 2, l_pull: float = 0.6) -> np.ndarray` — Lab: keep L detail, move part mean L by `l_pull` toward the target L, set a/b to the target.
  - Manifest params (plain JSON schema + widgets): `mode` (enum auto|manual, default auto, `x-widget: segmented`), `palette` (`{name: str, colors: [hex] 2–8}`, `x-widget: palette`, `x-presets`: ~12 named palettes including `{"name": "Coral Bay", ...}`), `seed` (integer, default 1, `x-widget: seed`), `count` (integer 1–24 default 8, `x-show-if: {mode: auto}`), `part_colors` (object part key → hex, `x-widget: part-colors`, `x-show-if: {mode: manual}`). Inputs image min 1 max 1; outputs `["images"]`; `runs_on` "Python · Lab".
  - Fewer than two parts → `{"error"}`-free failure: `main.py` raises so the run fails with `PLUGIN_BAD_INPUT`-equivalent message "This item needs at least two parts to recolour" (use the shim's error path).

- [ ] **Step 1: Write failing tests**
  - `test_label_map_smallest_wins`: laces mask inside upper mask → laces pixels labelled laces.
  - `test_adjacency_detects_touching_and_not_far`.
  - `test_assignments_distinct_and_deterministic`: same seed → same list; different seed → different first assignment; 4 parts × 5 colours, count 24 → 24 distinct, none with a touching pair equal.
  - `test_assignments_returns_fewer_when_exhausted`: 2 touching parts × 2 colours, count 8 → 2.
  - `test_recolor_keeps_outside_pixels_and_detail`: pixels with label -1 unchanged; inside a part, the std of L is within 10% of the source's.
  - `test_recolor_plugin_24_options_zero_model_calls` (mock providers, masks cached): 24 option items, image/reasoning provider call counts 0.
  - `test_recolor_plugin_one_part_fails_clearly`.
  - `test_recolor_manual_mode_uses_part_colors`: one image; the given part's mean a/b ≈ the target's (ΔE < 8).
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS**; full backend suite.
- [ ] **Step 5: Commit** `feat(plugins): Variation · Color — part-wise palette recolour, no generation`

### Task 6: Knob widgets on the node card

**Files:**
- Modify: `frontend/src/plugins/nodeLogic.ts` (`Field`, `paramFields`), `frontend/src/plugins/NodeCard.tsx`
- Create: `frontend/src/plugins/widgets/{Segmented,PaletteField,SeedButton,PartColors,FrameSlot,PromptField}.tsx`
- Test: `frontend/src/plugins/nodeLogic.test.ts`, `frontend/src/plugins/widgets/*.test.tsx`

**Interfaces:**
- Consumes: manifests from Tasks 4, 5, 8, 9 (`x-widget`, `x-presets`, `x-swap-with`, `x-describe`); item parts from the existing analysis query; board items' `palette` for board palettes.
- Produces:
  - `Field.widget?: 'segmented' | 'palette' | 'seed' | 'part-colors' | 'frame' | 'prompt'`, `Field.presets?`, `Field.swapWith?`, `Field.describe?`.
  - `paramFields` maps `x-widget` → `widget`; unknown widgets fall back to today's field type.
  - Describe calls `describeNode(nodeId): Promise<{prompt: string}>` (`POST /api/nodes/{id}/describe`, Task 9).

- [ ] **Step 1: Write failing tests**
  - `paramFields reads x-widget and presets`; `unknown x-widget falls back to string`.
  - `Segmented saves the chosen enum`; `SeedButton saves a new integer different from the current`.
  - `PaletteField lists presets and board palettes, edits one swatch, copies hex list`.
  - `PartColors lists the input item's parts by label and saves {key: hex}`.
  - `FrameSlot accepts a dropped/picked image item id; swap exchanges two linked slots`.
  - `PromptField Describe fills the text from describeNode and is disabled while locked`.
- [ ] **Step 2: Run, expect FAIL** — `cd frontend && npx vitest run src/plugins`
- [ ] **Step 3: Implement**, matching the round 2 card styles; widgets respect `readOnly` (demo lock).
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `feat(plugins-ui): palette, seed, segmented, part colour, frame and prompt widgets`

### Task 7: fal client and long jobs

**Files:**
- Create: `backend/app/providers/fal.py`, `backend/app/plugins/longjob.py`
- Modify: `backend/app/providers/__init__.py` (`get_fal`), `backend/app/plugins/service.py` (`execute_run`, `recover_stuck_runs`), `backend/app/plugins/runners.py` (`_run_model` dispatch)
- Test: `backend/tests/unit/providers/test_fal.py`, `backend/tests/integration/plugins/test_longjob.py`

**Interfaces:**
- Produces:
  - `FalClient(key: str, http: httpx.Client | None = None)` with `upload(data: bytes, mime: str) -> str` (URL), `submit(endpoint: str, payload: dict) -> str` (request id), `status(endpoint, request_id) -> Literal["IN_QUEUE","IN_PROGRESS","COMPLETED","FAILED"]`, `result(endpoint, request_id) -> dict`, `download(url: str, max_bytes: int) -> bytes`. Uses fal's queue REST API (`queue.fal.run`), `Authorization: Key <FAL_KEY>`. `MockFal` for tests (scriptable statuses, call log).
  - `get_fal(settings) -> FalClient | MockFal` (mock when `MODEL_PROVIDER`-style test setting is mock, matching the other factories).
  - `longjob.run_fal(session, run, endpoint, payload, cap: Literal["mesh","video"], progress) -> dict` — checks the cap, submits once, stores `external_json`, commits, polls every `FAL_POLL_S` until COMPLETED / FAILED / `FAL_TIMEOUT_S`, returns the result dict; on FAILED / timeout / submit error refunds the cap and raises `PluginError("PLUGIN_MODEL_FAILED", ...)`.
  - `longjob.resume(session, run) -> dict` — polls a stored request id without submitting.
  - `recover_stuck_runs`: runs with `external_json.request_id` and status running are re-enqueued as a resume job (`plugin_resume`) instead of failed; others behave as today.
  - Model handlers registry in runners: `MODEL_HANDLERS: dict[ModelName, Callable]`, `image.edit`/`image.generate` unchanged; `mesh.from_image` and `video.generate` filled by Tasks 8–9.

- [ ] **Step 1: Write failing tests**
  - `test_fal_submit_status_result_headers` (httpx MockTransport): auth header `Key k`, submit returns request id, result parsed.
  - `test_run_fal_happy_path_charges_once`.
  - `test_run_fal_failed_refunds`, `test_run_fal_timeout_refunds` (`FAL_TIMEOUT_S=0`).
  - `test_restart_resumes_without_resubmit`: a run left running with `external_json` → `recover_stuck_runs` → resume → MockFal submit count stays 1, cap slots used stays 1, run ends done.
  - `test_cap_reached_no_submit`: limit 0 → 429 surfaced as run failure `DAILY_LIMIT`, submit count 0.
  - `test_download_over_cap_rejected`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**. Verify current fal queue endpoints / response shapes from fal docs before coding the real client; record the endpoint ids chosen in `config.py` defaults with a comment citing the doc URL.
- [ ] **Step 4: Run, expect PASS**; full backend suite.
- [ ] **Step 5: Commit** `feat(plugins): fal queue client and resumable long jobs`

### Task 8: 3D model (`mesh`) — model item and writeback

**Files:**
- Modify: `backend/app/plugins/builtin/mesh/plugin.json`, `backend/app/plugins/runners.py` (`mesh.from_image` handler), `backend/app/plugins/writeback.py` (`model3d`), `backend/app/api/items.py` / media route (serve `.glb` as `model/gltf-binary`)
- Test: `backend/tests/integration/plugins/test_mesh_plugin.py`

**Interfaces:**
- Consumes: `run_fal` (Task 7), `cutout` via `load_builtin_module("cleanup", "cutout")` + `locate_object` (Tasks 2, 4).
- Produces:
  - Manifest: runner `model`, model `mesh.from_image`, inputs image 1–1, params `quality` (enum fast|detailed default fast, `x-widget: segmented`), `texture` (boolean default true); outputs `["model3d"]`; `requires: ["FAL_KEY"]`; `runs_on` "fal · Hunyuan3D".
  - Output shape (in-process, not JSON): `{"model3d": [{"glb": bytes, "poster": bytes, "caption": str}]}`; `validate_output` accepts bytes for this kind only from the model runner.
  - Writeback creates `BoardItem(kind="model", origin="generated", rights_status="generated", mime="model/gltf-binary", storage_path=<glb>, thumb_path=<poster thumb>, parent_item_id=source)` beside the node; poster = the cleaned cut-out (server-side GLB rendering is out of scope).

- [ ] **Step 1: Write failing tests**
  - `test_mesh_uploads_cleaned_cutout` (MockFal): uploaded bytes decode to RGBA with transparent corners.
  - `test_mesh_creates_model_item` with poster thumb and a stored `.glb`; media route returns `model/gltf-binary`.
  - `test_mesh_quality_picks_endpoint`: fast → `FAL_MESH_FAST`, detailed → `FAL_MESH_DETAILED`.
  - `test_mesh_not_connected_without_key`.
  - `test_mesh_glb_over_50mb_fails_and_refunds`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS**; full backend suite.
- [ ] **Step 5: Commit** `feat(plugins): connect 3D via fal Hunyuan3D; model items`

### Task 9: Animate (`video`) and Describe

**Files:**
- Modify: `backend/app/plugins/builtin/video/plugin.json`, `backend/app/plugins/runners.py` (`video.generate` handler), `backend/app/plugins/writeback.py` (`video` output via `ingest_video`), `backend/app/api/plugins.py` (`POST /nodes/{id}/describe`), `backend/app/plugins/service.py` (frame param validation)
- Test: `backend/tests/integration/plugins/test_video_plugin.py`, `backend/tests/integration/api/test_describe_api.py`

**Interfaces:**
- Consumes: `run_fal` (Task 7), reasoning provider, `ingest_video`.
- Produces:
  - Manifest: runner `model`, model `video.generate`, inputs image 1–1, params `type` (enum standard|pro default standard, segmented), `duration` (enum 5|10 default 5 — integer enum), `prompt` (string, `x-widget: prompt`, `x-describe: true`), `start` (string item id, `x-widget: frame`, `x-swap-with: end`), `end` (string item id, optional, `x-widget: frame`, `x-swap-with: start`); outputs `["video"]`; `requires: ["FAL_KEY"]`.
  - Start defaults to the wired input when `start` is empty. Each frame reference is validated at run start: same board, kind image, not removed, not staged — else `PLUGIN_BAD_INPUT` before any cap or submit.
  - `POST /api/nodes/{id}/describe` → `{"prompt": str}`; takes a `"render"` slot, refunds on failure; one reasoning call with the start frame; locked in demo mode like other writes.
  - Writeback `video`: bytes → `ingest_video(session, board_id, data, meta)` with `origin="generated"`, placed beside the node.

- [ ] **Step 1: Write failing tests**
  - `test_video_endpoint_by_type`, `test_video_sends_start_and_end_urls`, `test_video_swap_order_respected`.
  - `test_video_bad_end_frame_no_submit` for deleted / note / other-board ids; cap slots used 0.
  - `test_video_creates_video_item_with_frames`.
  - `test_describe_returns_prompt_and_counts_render`, `test_describe_refunds_on_failure`, `test_describe_locked_in_demo`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS**; full backend suite.
- [ ] **Step 5: Commit** `feat(plugins): connect Animate via fal image-to-video; Describe`

### Task 10: Board — options, inline video, 3D viewer

**Files:**
- Modify: `frontend/src/canvas/ItemNode.tsx`, `frontend/src/canvas/ItemToolbar.tsx`, `frontend/src/plugins/NodeCard.tsx` (Clear options), `frontend/src/api.ts` / `queries.ts` (`keepOption`, `clearOptions`), `frontend/src/canvas/history.ts` (clear is undoable)
- Create: `frontend/src/canvas/VideoOverlay.tsx`, `frontend/src/canvas/ModelViewer.tsx` (lazy `@google/model-viewer`)
- Test: matching `*.test.tsx`

**Interfaces:**
- Consumes: Task 3 endpoints, `Item.option_run_id`, `kind: 'model'`.
- Produces:
  - Option items draw a light dashed outline; the item toolbar shows **Keep** for options.
  - Node card shows **Clear options (n)** when its runs have flagged items; Clear is one undo step that restores all removed options.
  - Video items: click toggles inline playback in an HTML overlay positioned over the Konva node (muted, loops), follows pan/zoom; Escape / click outside pauses.
  - Model items: poster on canvas with a "3D" badge; open → overlay viewer (orbit, zoom) + **Download .glb**; the viewer module is loaded with `import()` only when opened.

- [ ] **Step 1: Write failing tests**
  - `option item renders outline and Keep`; `Keep calls keepOption and removes outline`.
  - `Clear options removes flagged items and undo restores them`.
  - `video item click plays, second click pauses`.
  - `model item opens viewer lazily (dynamic import called once) and download link points at the glb`.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement**; add `@google/model-viewer` (pin an exact version ≥2 weeks old) to `frontend/package.json`.
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `feat(board): option outlines, keep/clear, inline video, 3D viewer`

### Task 11: End-to-end, docs, agent check

**Files:**
- Create: `frontend/tests/e2e/round3.spec.ts`
- Modify: `docs/plugins.md` (`needs`, widgets, output kinds, caps), `README.md` (one paragraph), `backend/tests/integration/agent/` (a `run_plugin("recolor", …)` test)
- Test: the files above

- [ ] **Step 1: Write the e2e** (mock providers, mock fal): wire Variation to a seeded analysed shoe → Generate 24 → 24 option tiles; Shuffle → different first tile; keep 2, Clear → 2 remain; undo restores; Clean-up makes one cut-out; with mock `FAL_KEY` 3D produces a model item that opens the viewer; Animate produces a video that plays; without `FAL_KEY` both show "not connected".
- [ ] **Step 2: Agent test**: `run_plugin("recolor", [item], {"mode":"auto","palette":{...},"seed":3,"count":4})` returns 4 `item_ids`.
- [ ] **Step 3: Run** `make e2e` and the agent test, expect PASS; then backend, frontend, lint all green.
- [ ] **Step 4: Docs**: document `needs`, each `x-widget`, `model3d` / `video` outputs, `FAL_KEY`, and the caps table.
- [ ] **Step 5: Commit** `test(e2e): round 3 plugins; docs for widgets, masks and fal`

---

## Dependencies and parallel lanes

- Task 1 first (everything depends on it).
- Then three lanes that touch different files, safe to run in parallel worktrees branched from Task 1's commit and merged back in order:
  - **Lane A (python plugins):** Task 2 → Task 4 → Task 5 (Task 3 merged before Task 5's integration test).
  - **Lane B (options):** Task 3.
  - **Lane C (fal):** Task 7 → Task 8 → Task 9 (Task 8 needs Task 4's `cutout`; rebase on Lane A after Task 4).
  - **Lane D (frontend):** Task 6 and Task 10 (Task 10 after Task 3's endpoints exist; mock them in tests until then).
- Task 11 last, after all lanes merge.
