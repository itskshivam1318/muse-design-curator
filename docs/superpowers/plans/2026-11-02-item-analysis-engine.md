# Item Analysis Engine and Exploration Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the board-wide lens with per-item analysis (image, UI screenshot, text), expose the
loop analyse → label → extract → explore → render → keep as service functions + endpoints, and replace
chips/drawer/axis rows with part callouts and flower exploration on the canvas.

**Architecture:** A new backend package `app/analysis/` owns per-item parts and dimensions (one Spark
call per item, lazy SAM, merge that preserves `source="you"`). `app/render/` picks a renderer per item
type and composites edits back inside the part's region. Explore/keep/check/profile/vocab read a per-item
`AttributeSpec` (`spec_for(row)`) instead of the lens. The frontend gets `src/map/` (callouts, flowers,
free-space layout) and drops `ItemChips`, `AxisLayer`, `AxisPopover`, the Explore drawer and Vary.

**Tech Stack:** FastAPI, SQLAlchemy 2, alembic, pydantic v2, Pillow/numpy (backend, `uv run pytest`);
React + react-konva + TanStack Query, vitest, Playwright (frontend).

**Spec:** `docs/superpowers/specs/2026-11-02-item-analysis-engine-design.md` (read it first).

## Global Constraints

- Phase-1 item types: **image, text (notes and pasted text), UI screenshot**. Video's chosen frame is analysed as an image. Code/graph/flowchart: out.
- Dimension `type` ∈ `physical | abstract`; region kind ∈ `mask | box | text_range`; source ∈ `ai | you`. These are the only fixed vocabularies in code (domain-free guard test must still pass).
- Dimension value kinds stay today's: `enum, ordinal, number, boolean, color, text, shape` (`app/domain/kinds.py`).
- **One Spark call per item** for analyse. SAM runs only on hover/open/extract of an image part (cached in `PartMask`). UI boxes and text ranges come back with the analyse call; SAM is never used for UI.
- Explore never generates media. Options are notes until rendered.
- Render for a physical dimension edits the whole image, then composites back only pixels inside the region (feathered). Abstract dimensions are whole-image edits labelled "whole image, no mask".
- Board items never move because of a flower. Flowers only use free space; opening one never moves another; placement is deterministic; any number may be open.
- **No board re-analysis.** Existing items keep their attributes: with a part → physical; without → abstract. Single items can be re-run via `analyse`.
- **No agent** in this phase. Each loop function has one pydantic request/result schema defined once in `app/analysis/api_schemas.py`.
- **Vary is retired**: its UI is removed; `/runs` endpoints return `410 VARY_RETIRED`; tables stay.
- Built-in renderers on every board: Muse Image (image + UI) and Spark rewrite (text). "Connect a renderer" only when nothing accepts the item.
- Per-board daily limits: `ANALYSE_PER_BOARD_PER_DAY = 300` (analyse, extract, explore) and `RENDER_PER_BOARD_PER_DAY = 60`. Over limit → HTTP 429 `DAILY_LIMIT`, message exactly `Daily limit reached for this board, try tomorrow.`
- Flower collapsed state persists in browser `localStorage` (key `muse.flowers.collapsed.<boardId>`), wrapped in try/catch.
- `DEMO_MODE` guards apply to every new mutating endpoint (use the same dependency the existing mutating routes use in `app/api/deps.py`).
- Mock providers cover every new path; `make test`, `make lint`, `make e2e` run offline.

## Review Focus

1. **An item the model can't make sense of** (blank image, one-word note, empty Spark answer) — analyse stores zero parts and only abstract dimensions, `parse_status="completed"`, no crash; the UI shows just the "Whole item" callout. → test in Task 4.
2. **User edits vs re-analysis** — a part/dimension the person added, renamed or a value they set survives `analyse(item)` re-run, and a dimension the person removed is not re-added. → test in Task 4.
3. **Extract on a part whose mask is empty or the box is degenerate** — returns 422 `REGION_EMPTY`, creates no item. → test in Task 6.
4. **Crowded board** — opening a flower next to an item boxed in on all sides still places petals with zero overlap (pushes outward), and the existing items' positions are byte-identical before/after. → test in Task 13.
5. **Daily limit hit mid-flow** — a render rejected by the limit leaves the option `open` (not stuck `visualizing`) and the UI shows the limit message. → test in Task 10.

---

## File Structure

Backend (new):
- `backend/alembic/versions/0008_item_analysis.py` — schema changes + backfill.
- `backend/app/analysis/types.py` — `PartOut`, `DimensionOut`, `Analysis`, `Region` pydantic models; `ANALYSIS_SCHEMA`.
- `backend/app/analysis/spec.py` — `spec_for(row)`; `dimension_type(row)`.
- `backend/app/analysis/analysers.py` — content loading + prompt + Spark call per type.
- `backend/app/analysis/service.py` — `analyse`, merge, job, events.
- `backend/app/analysis/locate.py` — lazy region resolution.
- `backend/app/analysis/label.py` — label operations.
- `backend/app/analysis/extract.py` — cut-out into a new item; `free_slot`.
- `backend/app/analysis/context.py` — board context text, learned section, board dimension offers.
- `backend/app/analysis/limits.py` — per-board daily counters.
- `backend/app/analysis/api_schemas.py` — request/result schemas for the six functions.
- `backend/app/api/analysis.py` — routes.
- `backend/app/render/registry.py`, `backend/app/render/composite.py`, `backend/app/render/rewrite.py`.

Backend (modified): `db/models.py`, `config.py`, `extraction/service.py` (enqueue switch only), `explore/service.py`, `explore/visualize.py`, `explore/keep.py`, `explore/check.py`, `explore/vocab.py`, `board/profile.py`, `feedback/service.py`, `plugins/writeback.py`, `plugins/manifest.py`, `api/runs.py`, `api/schemas.py`, `main.py` (router), `providers/reasoning.py` (mock).

Frontend (new): `src/map/layout.ts`, `src/map/Callouts.tsx`, `src/map/RegionOverlay.tsx`, `src/map/Flower.tsx`, `src/map/PetalCard.tsx`, `src/map/collapse.ts`, `src/map/useMap.ts`, tests beside each; `tests/e2e/map.spec.ts`.
Frontend (modified): `src/api.ts`, `src/queries.ts`, `src/canvas/Canvas.tsx`, `src/canvas/ItemToolbar.tsx`, `src/canvas/NoteNode.tsx`, `src/panels/registerPanels.ts`.
Frontend (deleted): `src/canvas/ItemChips.tsx`, `src/canvas/AxisLayer.tsx`, `src/canvas/AxisPopover.tsx`, `src/canvas/axis.ts` (keep `chipSource` → move to `src/map/source.ts`), `src/panels/ExplorePanel.tsx`, `src/panels/VaryPanel.tsx`, `src/vary/`, and their tests.

---

### Task 1: Schema for parts, dimension types and content types

**Files:**
- Create: `backend/alembic/versions/0008_item_analysis.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/integration/db/test_item_analysis_migration.py`, `backend/tests/unit/db/test_item_parts.py`

**Interfaces:**
- Produces (models):
  - `ItemPart` table `item_parts`: `id` (`_id("part")`), `item_id` FK board_items, `key: str` (snake), `label: str`, `region_kind: str` ∈ `REGION_KINDS = ("mask", "box", "text_range")`, `region_json: Any` (box `[x0,y0,x1,y1]` 0..1, text_range `[start,end]`, mask `null` until located), `mask_path: str | None`, `source: str` ∈ `("ai","you")`, `removed: bool` default False (user removal tombstone), `created_at`. Unique `(item_id, key)`.
  - `ItemAttribute` new columns: `dim_type: str` ∈ `DIM_TYPES = ("physical","abstract")` default `"abstract"`; `prompt: str | None`; `spec_json: Any` (serialized `AttributeSpec`); `removed: bool` default False.
  - `BoardItem` new columns: `content_type: str | None` ∈ `CONTENT_TYPES = ("image","ui","text")`; `extracted_part: str | None`.
  - `Board` new columns: `learned_json: Any`; `dimensions_json: Any` (accepted board dimensions: list of `{label, dim_type, kind}`); `declined_json: Any`.
- Migration `0008` revises `0007` (check `down_revision` string in `0007_round2.py`). Backfill: `dim_type = 'physical' WHERE part IS NOT NULL ELSE 'abstract'`; `content_type = 'text'` for `kind='note'`, `'image'` for `kind in ('image','video')`; for each distinct `(item_id, part)` among attributes insert an `item_parts` row `key=part, label=part.replace('_',' ').capitalize(), region_kind='mask', source='ai'`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/db/test_item_analysis_migration.py
def test_backfill_types_and_parts(migrated_with_legacy_rows):  # fixture: run 0007, insert an image item
    s = migrated_with_legacy_rows                              # with attrs hand_style(part=hands), overall(part=None)
    assert attr(s, "hand_style").dim_type == "physical"
    assert attr(s, "overall").dim_type == "abstract"
    parts = s.scalars(select(ItemPart)).all()
    assert [(p.key, p.region_kind, p.source) for p in parts] == [("hands", "mask", "ai")]
    assert item(s).content_type == "image"

# tests/unit/db/test_item_parts.py
def test_part_key_unique_per_item(session): ...  # second ItemPart(item_id, key="hands") → IntegrityError
def test_region_kind_checked(session): ...       # region_kind="blob" → IntegrityError
```

Write the `migrated_with_legacy_rows` fixture by following how existing migration tests in `tests/integration/db/` upgrade to a revision and insert rows.

- [ ] **Step 2: Run, expect FAIL** — `cd backend && uv run pytest tests/integration/db/test_item_analysis_migration.py tests/unit/db/test_item_parts.py -v` → import/attribute errors.
- [ ] **Step 3: Add the columns/table/check constraints to `models.py` and write `0008_item_analysis.py`** (batch_alter_table for SQLite, as `0007` does).
- [ ] **Step 4: Run, expect PASS**; then `uv run alembic heads` shows a single head `0008`.
- [ ] **Step 5: Commit** `feat(db): item parts, dimension types, content types (0008)`

---

### Task 2: Per-item spec and analysis types

**Files:**
- Create: `backend/app/analysis/__init__.py`, `backend/app/analysis/types.py`, `backend/app/analysis/spec.py`
- Test: `backend/tests/unit/analysis/test_spec.py`, `backend/tests/unit/analysis/test_types.py`

**Interfaces:**
- Produces:
  - `class Region(BaseModel)`: `kind: Literal["mask","box","text_range"]`, `box: list[float] | None` (4 floats 0..1), `range: list[int] | None` (2 ints, start<end), `mask_url: str | None`.
  - `class PartOut(BaseModel)`: `key: str`, `label: str`, `region_kind`, `region: list[float] | list[int] | None`.
  - `class DimensionOut(BaseModel)`: `key: str`, `label: str`, `type: Literal["physical","abstract"]`, `part: str | None`, `prompt: str | None`, `kind: AttrKind`, `value: Any`, `confidence: float`, `vocabulary: list[str] = []`, `scale: list[str] = []`, `min: float | None`, `max: float | None`, `unit: str | None`. Validator: `type=="physical"` ⇔ `part is not None`; abstract requires `prompt`.
  - `class Analysis(BaseModel)`: `content_type: Literal["image","ui","text"]`, `summary: str`, `parts: list[PartOut]` (max 8), `dimensions: list[DimensionOut]` (max 20).
  - `ANALYSIS_SCHEMA: dict` — strict JSON schema (passes `strict_schema`) matching `Analysis` for Spark; schema title `"item_analysis"`.
  - `spec_for(row: ItemAttribute, lens: LensSpec | None = None) -> AttributeSpec` — from `row.spec_json` when set; else the lens attribute with that key; else a `TextSpec(key, label, category=row.category)`.
  - `spec_from_dimension(d: DimensionOut) -> AttributeSpec` — builds the right `*Spec` from `kind` + vocabulary/scale/min/max/unit; `open_vocabulary=True` for enums.
  - `dimension_type(row: ItemAttribute) -> Literal["physical","abstract"]`.

- [ ] **Step 1: Failing tests**

```python
def test_spec_for_prefers_stored_spec(): row.spec_json = EnumSpec(...).model_dump(); assert spec_for(row).kind == "enum"
def test_spec_for_falls_back_to_lens_then_text(): ...  # no spec_json + lens has key → lens spec; neither → TextSpec
def test_physical_needs_part_abstract_needs_prompt(): ...  # ValidationError both ways
def test_spec_from_dimension_ordinal_keeps_scale(): assert spec_from_dimension(d).scale == ["low","mid","high"]
def test_analysis_schema_is_strict(): assert strict_schema(ANALYSIS_SCHEMA) == ANALYSIS_SCHEMA
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/unit/analysis -v`.
- [ ] **Step 3: Implement** the models and functions above.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(analysis): per-item dimension types and spec_for`

---

### Task 3: Analysers (one Spark call per item, all three types)

**Files:**
- Create: `backend/app/analysis/analysers.py`
- Modify: `backend/app/providers/reasoning.py` (mock only)
- Test: `backend/tests/unit/analysis/test_analysers.py`

**Interfaces:**
- Consumes: `Analysis`, `ANALYSIS_SCHEMA` (Task 2); `get_reasoning(settings).structured(images, schema, prompt)`; `_image_for` from `extraction/service.py`.
- Produces:
  - `@dataclass ItemContent`: `item_id: str`, `kind: str`, `image: bytes | None`, `text: str | None`.
  - `load_content(session, item: BoardItem) -> ItemContent` — image/video → image bytes; note → `note_text`; otherwise `AppError(400,"UNSUPPORTED_ITEM")`.
  - `build_prompt(content: ItemContent, board_context: str, hints: Hints) -> str` where `@dataclass Hints`: `board_dimensions: list[dict]`, `abstract_definitions: list[dict]` (label+prompt in use on the board), `you_parts: list[str]`, `you_dimensions: list[str]`, `removed: list[str]`.
  - `run_analyser(content: ItemContent, board_context: str, hints: Hints) -> Analysis` — one `structured()` call; validates into `Analysis`; drops parts/dimensions that fail validation instead of failing the whole call; for text content forces `content_type="text"` and drops any `box`; for image content drops `text_range` parts; for `content_type=="ui"` parts must be `box`; for `"image"` parts are `mask` with `region=None`.
- Prompt requirements (exact intent, wording is the builder's): classify `image` vs `ui` (UI = a screenshot of software); name up to 8 parts; per part its physical dimensions; 2–6 abstract dimensions with a one-sentence `prompt` each; **reuse labels from `abstract_definitions` and `board_dimensions` when they apply**; never propose anything in `removed`; text parts give char ranges into the given text.
- Mock: `MockReasoningProvider.structured` returns a canned deterministic `Analysis` dict when `schema.get("title") == "item_analysis"`: image → 2 parts (`body` mask, `detail` mask), dims `body_colour` (physical, color), `detail_style` (physical, enum), `subject` + `medium` (abstract, text/enum); ui → parts `header`, `primary_button` with boxes `[0,0,1,0.15]`, `[0.35,0.8,0.65,0.9]`; text → part `opening` range `[0, min(len,40)]`, abstract `tone`, `length`. Classification in the mock: images whose width/height ratio ≥ 1.6 → `ui`.

- [ ] **Step 1: Failing tests**

```python
def test_note_is_text_with_ranges(): a = run_analyser(ItemContent(..., text="Warm field watch, legible."), "", Hints.empty())
    assert a.content_type == "text" and a.parts[0].region_kind == "text_range" and a.parts[0].region == [0, 26]
def test_wide_image_is_ui_with_boxes(): ...  # 1600x900 png → content_type "ui", every part box
def test_bad_dimension_dropped_not_fatal(monkeypatch): ...  # fake structured returns one physical dim without part → dropped, others kept
def test_prompt_carries_reuse_and_removed(): p = build_prompt(...); assert "Medium" in p and "strap_stitching" in p
def test_empty_answer_gives_empty_analysis(monkeypatch): ...  # {"parts":[],"dimensions":[]} → Analysis with no parts
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `analysers.py` and the mock branch.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(analysis): image, UI and text analysers in one Spark call`

---

### Task 4: analyse service, merge that keeps your edits, and the job switch

**Files:**
- Create: `backend/app/analysis/service.py`
- Modify: `backend/app/extraction/service.py` (route `request_parse`/`parse_item_job` to analysis for new items), ingest call sites that enqueue `parse_item` (grep `"parse_item"`).
- Test: `backend/tests/integration/test_analysis_service.py`

**Interfaces:**
- Consumes: Tasks 1–3; `board_context(session, board_id) -> str` and `hints_for(session, board_id, item_id) -> Hints` (Task 9 provides them; until then implement them in `context.py` as returning `board.context` and empty hints — Task 9 fills them in).
- Produces:
  - `analyse(session, item_id: str) -> Analysis` — runs synchronously inside the job; writes parts + dimensions; sets `item.content_type`; `parse_status` `processing` → `completed` (or `failed` with `parse_error_code`); publishes `item.analysed` `{item_id}`; then calls `refresh_learned` (Task 9) after commit.
  - `request_analyse(session, item_id: str) -> None` — claim like `request_parse` (same CLAIMABLE logic), count against limit `"analyse"` (Task 8; until Task 8 lands, no-op), enqueue job `"analyse_item"`.
  - `merge_analysis(session, item: BoardItem, a: Analysis) -> None` — rules:
    - rows/parts with `source="you"` are never overwritten or deleted;
    - rows/parts with `removed=True` are never re-added;
    - `source="ai"` rows not in the new analysis are deleted **unless** an `Exploration` exists for `(item_id, key)` — then kept and marked `status="stale"` (“old dimension, not found on this item”);
    - new/updated ai rows store `spec_json = spec_from_dimension(d).model_dump()`, `dim_type`, `prompt`, `part`, `value_json`, `confidence`, `source="model"`, `status="read"` (keep the existing ItemAttribute status/source vocabulary).
  - Job `"analyse_item"` registered with `jobs.register`. All item creation paths that enqueued `parse_item` now enqueue `analyse_item`. `parse_item` stays importable for legacy callers but is no longer enqueued.
- Existing items are **not** re-analysed (no migration job, no banner).

- [ ] **Step 1: Failing tests**

```python
def test_upload_runs_analyse_and_stores_parts(client): upload png → wait job → GET /items/{id}/analysis has 2 parts, ≥1 abstract dim
def test_rerun_keeps_you_rows_and_respects_removed(session): set value source=you; mark detail_style removed; analyse again
    → value unchanged, detail_style absent
def test_ai_row_with_exploration_goes_stale_not_deleted(session): ...
def test_blank_item_completes_with_no_parts(session, monkeypatch): ...  # Review Focus 1
def test_note_creation_enqueues_analyse(client): POST note → jobs enqueued "analyse_item"
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** service + enqueue switch.
- [ ] **Step 4: Run** the new tests, then the full suite `uv run pytest -q`; fix any test that asserted `parse_item` enqueueing for new items by updating it to `analyse_item`.
- [ ] **Step 5: Commit** `feat(analysis): analyse service and merge that keeps your edits`

---

### Task 5: Lazy regions (SAM on demand)

**Files:**
- Create: `backend/app/analysis/locate.py`
- Test: `backend/tests/integration/test_locate.py`

**Interfaces:**
- Consumes: `_part_mask` / `_mask_rel` / `masks_repo` from `extraction/service.py` (reuse, don't copy); `ItemPart`.
- Produces: `locate(session, item_id: str, part_key: str) -> Region`
  - `box`/`text_range` parts: return stored region, no model call.
  - `mask` parts: if `mask_path` set → return it; else run SAM with prompt = part label (1–3 words; truncate), cache in `PartMask`, store `mask_path` and bbox on the part, return. SAM failure → `AppError(502,"REGION_FAILED")`. Empty mask (ratio < 0.001) → `AppError(422,"REGION_EMPTY")`.
  - `mask_url` = `/api/media/masks/<file>` (follow how `api/media.py` serves stored files).

- [ ] **Step 1: Failing tests** — `test_box_part_needs_no_model` (segmentation provider patched to raise; still returns box); `test_mask_located_once_then_cached` (call twice; SAM called once); `test_empty_mask_is_422`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(analysis): resolve part regions on demand`

---

### Task 6: label and extract

**Files:**
- Create: `backend/app/analysis/label.py`, `backend/app/analysis/extract.py`
- Test: `backend/tests/integration/test_label.py`, `backend/tests/integration/test_extract.py`

**Interfaces:**
- Produces (`label.py`), all mark `source="you"` and write an `AttributeEvent`:
  - `add_part(session, item_id, label: str, region: Region | None) -> ItemPart` (key = snake of label; region None for images → `mask` located later from the label)
  - `rename_part(session, item_id, key, label) -> ItemPart`
  - `remove_part(session, item_id, key) -> None` (sets `removed=True`; its physical dimensions also `removed=True`)
  - `add_dimension(session, item_id, label, type, part: str | None, prompt: str | None, kind: AttrKind = "text") -> ItemAttribute`
  - `update_dimension(session, item_id, key, *, label=None, type=None, part=None, prompt=None) -> ItemAttribute`
  - `remove_dimension(session, item_id, key) -> None` (`removed=True`)
  - `set_content_type(session, item_id, content_type) -> BoardItem` (then `request_analyse`)
  - Value edits keep using the existing `edit_attribute` path, which now resolves the spec through `spec_for`.
- Produces (`extract.py`):
  - `free_slot(session, board_id, near: Bounds, size: tuple[float,float], gap: float = 40) -> tuple[float,float]` — first position to the right of `near` (then below, then left) whose rect does not intersect any non-removed, non-staged item; scans in steps of `gap`. Deterministic.
  - `extract(session, item_id, part_key) -> BoardItem` — image/UI: crop the region's bbox; for masks, alpha = mask (RGBA PNG); box → plain crop. Text: new note with the range's text. New item: `origin="generated"`, `rights_status` same as source if user_supplied else `"generated"`, `parent_item_id=item_id`, `extracted_part=part_key`, placed at `free_slot`; then `request_analyse`. (The `"analyse"` limit is wired in Task 8.) Empty region → 422 `REGION_EMPTY`, nothing created.

- [ ] **Step 1: Failing tests**

```python
def test_removed_part_not_readded_on_analyse(session): remove_part(...); analyse(...); assert part.removed and no new row
def test_add_dimension_abstract_needs_prompt(session): with pytest.raises(AppError): add_dimension(..., type="abstract", prompt=None)
def test_extract_mask_gives_rgba_child_beside_source(client): child.parent_item_id == src.id; child.extracted_part == "body";
    PNG mode "RGBA"; child.x >= src.x + src.w
def test_extract_text_range_makes_note(client): child.kind == "note" and child.note_text == text[0:26]
def test_free_slot_skips_occupied(session): item at right slot → returned slot is below it, no intersection
def test_extract_empty_region_creates_nothing(client): ...  # Review Focus 3
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(analysis): label edits and extract a part into its own item`

---

### Task 7: Explore and check on per-item dimensions; retire Vary; decouple lens readers

**Files:**
- Modify: `backend/app/explore/service.py`, `backend/app/explore/check.py`, `backend/app/explore/vocab.py`, `backend/app/explore/prompts.py`, `backend/app/board/profile.py`, `backend/app/feedback/service.py`, `backend/app/plugins/writeback.py`, `backend/app/api/runs.py`
- Test: `backend/tests/integration/api/test_explore.py` (update), `backend/tests/unit/explore/test_per_item_explore.py`, `backend/tests/integration/api/test_runs.py` (update)

**Interfaces:**
- Consumes: `spec_for`, `dimension_type` (Task 2); `board_context` (Task 9 stub).
- Changes:
  - `explore(...)`: no `LENS_REQUIRED`; `spec = spec_for(row, current_lens(...))` where `row` is the item's non-removed attribute with that key; missing → `AppError(400,"DIMENSION_NOT_ON_ITEM")`. The attribute list given to the prompt and the allowed `keeps` set = the item's own non-removed dimensions. Abstract dimensions add their `prompt` to the explore prompt; physical add "only the <part label> changes". Board context comes from `board_context(...)`.
  - `check_generated(...)`: dimensions held = the source item's own non-removed dimensions (resolved with `spec_for`).
  - `vocab.add_vocabulary`, `board/profile.py`, `feedback/service.py`, `plugins/writeback._fit`: resolve specs via `spec_for(row, lens)`; profile counts per-item dimensions grouped by **label** (case-insensitive) instead of lens keys.
  - `api/runs.py`: every route raises `AppError(410,"VARY_RETIRED","Vary has been replaced by Explore")`.
- [ ] **Step 1: Failing tests** — `test_explore_without_lens_on_item_dimension`; `test_explore_unknown_key_is_400_dimension_not_on_item`; `test_abstract_prompt_reaches_model` (spy on provider prompt contains the dimension prompt); `test_check_holds_items_own_dimensions`; `test_profile_groups_by_label_across_items`; `test_runs_return_410`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Delete Vary-only tests that test run behaviour; keep repo/model tests.
- [ ] **Step 4: Run** full `uv run pytest -q`, expect PASS.
- [ ] **Step 5: Commit** `feat(explore): per-item dimensions; retire Vary`

---

### Task 8: Per-board daily limits

**Files:**
- Create: `backend/app/analysis/limits.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/unit/analysis/test_limits.py`, plus one API test in `tests/integration/api/test_analysis_api.py` (Task 11 file; create it here if absent)

**Interfaces:**
- Produces: `check_and_count(board_id: str, kind: Literal["analyse","render"], settings: Settings | None = None) -> None` — uses `app.demo.windows` with keys `f"analyse:{board_id}"` / `f"render:{board_id}"` over `DAY_S`; over limit → `AppError(429,"DAILY_LIMIT","Daily limit reached for this board, try tomorrow.")` with `Retry-After` like `demo._limited`. `refund(board_id, kind)` removes the last entry (used when the work fails before calling a model).
- Settings: `ANALYSE_PER_BOARD_PER_DAY: int = 300`, `RENDER_PER_BOARD_PER_DAY: int = 60`.
- Wire into `request_analyse`, `extract`, `explore` (kind `"analyse"`), and `request_visualize` / render (kind `"render"`).
- [ ] **Step 1: Failing tests** — `test_limit_hits_at_setting` (setting 2 → third call 429 with exact message); `test_boards_counted_separately`; `test_refund_frees_slot`.
- [ ] **Step 2–4:** run FAIL → implement → run PASS.
- [ ] **Step 5: Commit** `feat(analysis): per-board daily limits for analyse and render`

---

### Task 9: Board context, learned section, board dimension offers

**Files:**
- Create/complete: `backend/app/analysis/context.py`
- Test: `backend/tests/integration/test_board_context.py`

**Interfaces:**
- Produces:
  - `board_context(session, board_id) -> str` — `"Board: <title>\nYour words: <board.context>\nWhat Muse has learned:\n- ..."` (learned lines from `learned_json`, max 12).
  - `hints_for(session, board_id, item_id) -> Hints` — board dimensions (`dimensions_json`), abstract definitions in use (distinct `(label, prompt)` of abstract rows on the board, most frequent first, max 12), the item's `you` and `removed` keys.
  - `refresh_learned(session, board_id) -> list[str]` — no model call; built from `board/profile.py` signals ("Dial colour: black · 9 of 12"), tensions ("Case shape: round 7 · cushion 5"), and kept vs dismissed option names per dimension ("Kept for Hand style: copper dauphine; not: gilt"). Stores `learned_json`; publishes `board.learned`.
  - `dimension_offers(session, board_id) -> list[Offer]` with `Offer(label, dim_type, kind, count, total)` — groups non-removed dimensions across items by `(label.lower(), dim_type, kind)` (+ part label for physical); offers groups with `count >= 2` not already in `dimensions_json` or `declined_json`.
  - `accept_offer(session, board_id, label, dim_type, kind)` → appends to `dimensions_json`; `decline_offer(...)` → appends to `declined_json`.
- [ ] **Step 1: Failing tests** — `test_offer_appears_at_two_items_not_one`; `test_accept_then_hint_reaches_prompt`; `test_declined_offer_not_shown_again`; `test_learned_lists_kept_and_rejected`; `test_your_words_never_changed_by_refresh`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(analysis): growing board context and board dimension offers`

---

### Task 10: Render — renderer registry, masked composite, Spark rewrite

**Files:**
- Create: `backend/app/render/__init__.py`, `backend/app/render/registry.py`, `backend/app/render/composite.py`, `backend/app/render/rewrite.py`
- Modify: `backend/app/explore/visualize.py`, `backend/app/plugins/manifest.py`, `backend/app/plugins/builtin/image/plugin.json`
- Test: `backend/tests/unit/render/test_composite.py`, `backend/tests/unit/render/test_registry.py`, `backend/tests/integration/api/test_visualize.py` (update)

**Interfaces:**
- Produces:
  - `@dataclass RendererInfo`: `id: str`, `title: str` (button line 1, e.g. `"Generate image"`, `"Rewrite passage"`), `detail: str` (line 2, e.g. `"Muse Image · inside the Hands mask"`, `"Muse Image · whole image, no mask"`, `"Muse Spark · this passage only"`), `builtin: bool`.
  - `renderers_for(session, item: BoardItem, row: ItemAttribute) -> list[RendererInfo]` — built-ins first: `muse_image` for content_type image/ui; `spark_rewrite` for text; then board-added plugins whose manifest has `renders: list[Kind]` containing the item kind. Empty list → UI shows "Connect a renderer".
  - Manifest: optional `renders: list[Kind] = []`; image plugin.json gets `"renders": ["image"]` (it is still listed as a built-in, not duplicated).
  - `composite_in_region(source: bytes, edited: bytes, region: Region, mask: np.ndarray | None, feather_px: int = 6) -> bytes` — resize `edited` to source size; alpha = mask (or box rect) Gaussian-feathered by `feather_px`; result PNG. Pixels where alpha==0 are byte-identical to source.
  - `rewrite_passage(text: str, rng: tuple[int,int] | None, instruction: str) -> str` — Spark `structured` with `{"text": str}`; replaces only `text[start:end]` (whole text when `rng` None).
  - `visualize(...)` now: picks renderer (request may pass `renderer_id`; default first), checks limit `"render"`, for images calls `provider.edit` then `composite_in_region` when the option's dimension is physical (region via `locate`), whole-image when abstract; for text creates a note with the rewritten text, `note_text` stored, and `generation_json.changed_range=[start, start+len(new)]`. Board-plugin renderers run through `plugins.service` with the plugin's `image.edit` model path (existing `PART_PROMPT`). Limit refusal leaves option `open` (Review Focus 5).
- [ ] **Step 1: Failing tests**

```python
def test_composite_outside_mask_identical(): out = composite_in_region(src, edited, box_region, None)
    assert np.array_equal(arr(out)[outside], arr(src)[outside])
def test_composite_inside_takes_edit(): mean diff inside > 0
def test_renderers_for_text_is_spark_rewrite(): [r.id for r in renderers_for(...)] == ["spark_rewrite"]
def test_renderer_detail_names_part(): renderers_for(image item, hands row)[0].detail == "Muse Image · inside the Hands mask"
def test_abstract_detail_says_no_mask(): ... == "Muse Image · whole image, no mask"
def test_rewrite_changes_only_range(): rewrite_passage("Aaa. Bbb. Ccc.", (5, 9), "louder")[:5] == "Aaa. " and endswith(" Ccc.")
def test_visualize_over_limit_leaves_option_open(client): ...  # 429 DAILY_LIMIT, option.status == "open"
```

- [ ] **Step 2–4:** FAIL → implement → PASS; full suite.
- [ ] **Step 5: Commit** `feat(render): renderer registry, in-region composite, passage rewrite`

---

### Task 11: Keep as a normal item + the HTTP surface for the loop

**Files:**
- Create: `backend/app/analysis/api_schemas.py`, `backend/app/api/analysis.py`
- Modify: `backend/app/explore/keep.py`, `backend/app/api/explore.py`, `backend/app/api/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/integration/api/test_analysis_api.py`, `backend/tests/integration/api/test_keep.py` (update)

**Interfaces:**
- `keep_take`: after un-staging, enqueue `analyse_item` for the kept item; position comes from the request (`at`) — the client computes it with the free-space layout; server falls back to `free_slot` near the source when absent.
- Routes (all mutating ones behind the demo guard dependency):
  - `GET  /api/items/{id}/analysis` → `AnalysisView {content_type, parse_status, parts: [PartView], dimensions: [DimensionView]}` where `PartView{key,label,region_kind,region,mask_url,source}` and `DimensionView{key,label,type,part,prompt,kind,value,confidence,source,status}` (removed rows omitted; stale rows included with `status:"stale"`).
  - `POST /api/items/{id}/analyse` → 202
  - `GET  /api/items/{id}/parts/{key}/region` → `Region`
  - `POST /api/items/{id}/parts` `{label, region?}`; `PATCH /api/items/{id}/parts/{key}` `{label}`; `DELETE /api/items/{id}/parts/{key}`
  - `POST /api/items/{id}/dimensions` `{label,type,part?,prompt?,kind?}`; `PATCH /api/items/{id}/dimensions/{key}`; `DELETE /api/items/{id}/dimensions/{key}`
  - `PATCH /api/items/{id}` accepts `content_type`
  - `POST /api/items/{id}/parts/{key}/extract` → `Item`
  - `GET  /api/items/{id}/dimensions/{key}/renderers` → `[RendererInfo]`
  - `POST /api/options/{id}/visualize` accepts optional `renderer_id`
  - `GET  /api/boards/{id}/context` → `{your_words, learned: [str], offers: [Offer]}`; `POST /api/boards/{id}/offers/accept|decline` `{label,dim_type,kind}`
  - `item_to_dict` adds `content_type`, `extracted_part`.
- [ ] **Step 1: Failing tests** — one happy-path test per route (status + shape), plus `test_kept_take_is_visible_and_analysed` (after keep: `staged == False`, job `analyse_item` enqueued) and `test_demo_mode_blocks_label_edits` (DEMO_MODE locked → 403 like other mutating routes).
- [ ] **Step 2–4:** FAIL → implement → PASS; `uv run pytest -q`; `make lint`.
- [ ] **Step 5: Commit** `feat(api): analysis, label, extract, renderers and board context routes`

---

### Task 12: Frontend API types and queries

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/queries.ts`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Produces (TS): `ContentType = 'image'|'ui'|'text'`; `RegionKind`; `Region {kind, box?, range?, mask_url?}`; `PartView`; `DimensionView` (with `type: 'physical'|'abstract'`); `AnalysisView`; `RendererInfo {id,title,detail,builtin}`; `Offer`; `BoardContextView`.
- API functions: `getAnalysis(itemId)`, `analyseItem(itemId)`, `getRegion(itemId, partKey)`, `addPart`, `renamePart`, `removePart`, `addDimension`, `updateDimension`, `removeDimension`, `setContentType`, `extractPart(itemId, partKey)`, `getRenderers(itemId, key)`, `visualizeOption(optionId, {at?, renderer_id?})` (extend existing), `getBoardContext(boardId)`, `acceptOffer`, `declineOffer`.
- Queries: `useAnalysis(itemId)` (key `['analysis', itemId]`, invalidated on SSE `item.analysed`), `useRegion(itemId, partKey, enabled)`, `useRenderers(itemId, key, enabled)`, `useBoardContext(boardId)` (invalidated on `board.learned`). Remove `useBoardLens` callers in later tasks, not here.
- [ ] **Step 1: Failing tests** — fetch-mock tests for `getAnalysis` URL + parse, `extractPart` POST path, `visualizeOption` body includes `renderer_id`; and a 429 response surfaces `message` `Daily limit reached for this board, try tomorrow.` through the existing error helper.
- [ ] **Step 2–4:** `cd frontend && npx vitest run src/api.test.ts` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(frontend): analysis API types and queries`

---

### Task 13: Free-space layout for callouts and flowers

**Files:**
- Create: `frontend/src/map/layout.ts`, `frontend/src/map/layout.test.ts`

**Interfaces:**
- Consumes: `Bounds`, `rectsIntersect`, `unionBounds` from `src/canvas/geometry.ts`.
- Produces:
  - `CALLOUT_W = 176`, `HUB_W = 150`, `HUB_H = 48`, `PETAL = 88`, `PETAL_KEPT = 104`, `RING = 175`, `PETAL_GAP = 12`.
  - `calloutSlots(item: Bounds, parts: {key: string; anchor: Point}[], obstacles: Bounds[]) -> Map<string, Bounds>` — each callout on the side of the item nearest its anchor (left/right/below), stacked without overlap, not over obstacles.
  - `placeFlower(input: { id: string; from: Point; dir: number /*radians*/; petals: number; kept: number[] }, obstacles: Bounds[]) -> FlowerLayout` where `FlowerLayout = { hub: Bounds; petals: Bounds[]; lines: [Point, Point][]; bounds: Bounds }`. Petals on an arc of ±115° around `dir` at radius `RING` (46° apart for 6, as in the Flower artboard). If the flower's `bounds` (with `PETAL_GAP` padding) intersects any obstacle, move the hub outward along `dir` in steps of 40 px (max 40 steps), then try `dir ± 30°`, `± 60°`.
  - `layoutFlowers(flowers: FlowerInput[], items: Bounds[], callouts: Bounds[]) -> Map<string, FlowerLayout>` — place in **stable order** (sorted by flower `id`, which is the exploration id, creation-ordered); each placed flower's bounds join the obstacles for the next. Never returns item positions (items are read-only input).
  - `visibleFlowers(layouts, viewport: Bounds) -> string[]` for culling.
- [ ] **Step 1: Failing tests**

```ts
it('petals never overlap items, callouts or other flowers', ...)        // 3 items, 4 flowers → all pairwise rectsIntersect false
it('opening a second flower does not move the first', ...)            // layoutFlowers([A]) A === layoutFlowers([A,B]) A (deep equal)
it('boxed-in item pushes the flower outward', ...)                    // Review Focus 4: 8 items around source; result clear; items untouched
it('is deterministic', ...)                                           // same input twice → identical output
it('callouts sit on the anchor side', ...)                            // anchor at left third → callout.x + w <= item.x
it('culls flowers outside the viewport', ...)
```

- [ ] **Step 2–4:** `npx vitest run src/map/layout.test.ts` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(map): deterministic free-space layout for callouts and flowers`

---

### Task 14: Part callouts, region hover, toolbar trim, remove chips/drawer/Vary

**Files:**
- Create: `frontend/src/map/Callouts.tsx`, `frontend/src/map/RegionOverlay.tsx`, `frontend/src/map/source.ts` (moved `chipSource`), tests beside each
- Modify: `frontend/src/canvas/Canvas.tsx`, `frontend/src/canvas/ItemToolbar.tsx`, `frontend/src/panels/registerPanels.ts`, `frontend/src/shell/LeftRail.tsx` (drop lens-waiting dot)
- Delete: `ItemChips.tsx(+test)`, `panels/ExplorePanel.tsx(+test)`, `panels/VaryPanel.tsx(+test)`, `src/vary/`

**Interfaces:**
- Consumes: `useAnalysis`, `useRegion`, `extractPart`, label API fns (Task 12); `calloutSlots` (Task 13).
- Produces:
  - `<Callouts item analysis view onOpenDimension(key) onHoverPart(key|null) />` — HTML overlay like the old `AxisLayer` (screen-space from `view`). One card per non-removed part: title = part label, small tag = `"SAM mask" | "box" | "passage"`, one button per physical dimension `"<label> · <value>"`, an **Extract** button, and "+ Add dimension". A dashed **"Whole item"** card with abstract dimensions (tag `"no mask"`) and "+ Add dimension". Leader line + anchor dot per part (anchor = region centre; for un-located masks the part's bbox from analysis if any, else item centre). Footer "+ Add part". Stale dimensions render greyed with title "old dimension, not found on this item".
  - `<RegionOverlay item region />` — mask image tinted `#ffd166` at 0.35 alpha with 2px outline for masks; rect for boxes; for text items `NoteNode` receives `highlight: [start,end] | null` and renders that span with a yellow background.
  - Hovering a callout or any of its dimension buttons sets the hovered part → `useRegion(item, part, enabled=true)` → overlay (loading: dashed outline of the part bbox).
  - `ItemToolbar` single selection: **Inspect · Not this · Remove** (+ Open source ↗); Explore/Vary buttons and the `V` shortcut removed; Compare for 2–4 unchanged.
  - Shortcut help text in `Canvas.tsx` updated: no Vary/Explore wording; "click a dimension on a part to explore it".
- [ ] **Step 1: Failing tests** (RTL)

```ts
it('renders one callout per part and a Whole item card for abstract dimensions')
it('hovering a callout requests its region and shows the overlay')
it('Extract calls extractPart with the part key')
it('toolbar has Inspect, Not this, Remove and no Explore')
it('stale dimension is shown greyed with its explanation')
```

- [ ] **Step 2–4:** FAIL → implement → PASS; `npx vitest run`; `npm run lint && npx tsc -b`.
- [ ] **Step 5: Commit** `feat(map): part callouts with region hover; drop chips, Explore drawer and Vary`

---

### Task 15: Flowers, petals and the petal card

**Files:**
- Create: `frontend/src/map/Flower.tsx`, `frontend/src/map/PetalCard.tsx`, `frontend/src/map/collapse.ts`, `frontend/src/map/useMap.ts`, tests beside each
- Modify: `frontend/src/canvas/Canvas.tsx`
- Delete: `AxisLayer.tsx(+test)`, `AxisPopover.tsx(+test)`, `axis.ts(+test)`; in `Canvas.tsx` remove `drawnAxes`/hidden-item filtering and `keptFollowers`

**Interfaces:**
- Consumes: `useExplorations`, existing explore actions in `src/explore/optionActions.ts` (`exploreItem`, dismiss, keep/unkeep, more/further/steer), `useRenderers`, `visualizeOption`, `layoutFlowers`, `visibleFlowers`.
- Produces:
  - `useMap(boardId, items, view) -> { flowers: FlowerModel[]; layouts: Map<string, FlowerLayout> }` — one `FlowerModel` per exploration whose source item is visible: `{id, itemId, key, label, from: Point /*callout edge*/, dir, options, collapsed}`; `dir` = angle from item centre to its callout.
  - `<Flower model layout view />` — dashed line callout→hub; hub pill `"<label>"` + sub `"<n> options · <k> kept"`; petals per option state:
    - `open` → note petal (white card, dashed border `#8d96a6`, name + distance tag);
    - `visualizing` → same + spinner;
    - `visualized` → result thumbnail (image) or excerpt with the changed span marked (text);
    - `kept` → `PETAL_KEPT` size, 3px `#1f8a5b` border;
    - drifted (check failed) → red border, never kept.
    - Collapse toggle on the hub; collapsed renders only a badge on the callout `"<label> · <n> options · <k> kept"`.
  - `<PetalCard option dimension item />` — name, distance tag, description, `Changes **<part>** · keeps <n> ✓`; render button from `useRenderers` (first renderer: title + detail lines); none → dashed "Connect a renderer" opening the Plugins rail panel; after render: check line (✓ green / ✕ red with drift text) and **Keep / Not this**, or **Retry, tighter mask / Drop** on drift; always **More like this** (explore `more`), **Branch** (explore from a kept result: selects the kept item), **Dismiss**. Daily-limit error shows `Daily limit reached for this board, try tomorrow.` inline.
  - `collapse.ts`: `isCollapsed(boardId, id)`, `setCollapsed(boardId, id, v)` over `localStorage` key `muse.flowers.collapsed.<boardId>`, try/catch, default false.
  - Keep: client passes `at` = free slot next to the petal computed with `layoutFlowers` obstacles; the kept item renders as a normal `ItemNode` (no hiding) and gets callouts when selected.
  - Only flowers in `visibleFlowers(..., viewport)` mount (smooth pan/zoom).
- [ ] **Step 1: Failing tests**

```ts
it('clicking a dimension opens a hub with note petals and generates nothing')   // no visualize call
it('petal card button names the renderer: "Generate image" / "Muse Image · inside the Hands mask"')
it('no renderer → "Connect a renderer"')
it('two flowers open at once both render')
it('collapse persists per board in localStorage and survives storage throwing')
it('kept result is an ordinary item on the board, not hidden')
it('drifted result shows Retry, tighter mask and no Keep')
```

- [ ] **Step 2–4:** FAIL → implement → PASS; full `npx vitest run`; lint + tsc.
- [ ] **Step 5: Commit** `feat(map): flowers with note petals, renderer-named render, keep as item`

---

### Task 16: Board context and offers in the existing board UI

**Files:**
- Modify: `frontend/src/panels/BoardSignals.tsx` (or the Library rail panel that shows the board brief today — find where `board.context` is edited), test beside it
- Modify: `frontend/src/panels/LensReview.tsx` usage: stop rendering the lens proposal for boards (no new lenses are proposed); keep the file if other code imports it, else delete.

**Interfaces:**
- Consumes: `useBoardContext`, `acceptOffer`, `declineOffer`.
- Produces: under the board's own words, a "What Muse has learned" list (read-only) and offer cards `"<label> · seen on <count> of <total> · Add to board / Keep item-only"`.
- [ ] **Step 1: Failing tests** — learned lines render; Add to board calls `acceptOffer` and the card disappears; Keep item-only calls `declineOffer`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(board): learned context and dimension offers`

---

### Task 17: End-to-end (offline, mock providers)

**Files:**
- Create: `frontend/tests/e2e/map.spec.ts`
- Modify: `frontend/tests/e2e/explore.spec.ts`, `demo-flow.spec.ts`, `round2.spec.ts` (replace chip/axis/drawer/Vary steps with callouts/flowers)

**Scenarios (each one `test`):**
1. Upload an image → select it → callouts "Body" and "Detail" and a "Whole item" card appear → hover "Body" → region overlay visible.
2. Click `Body colour · …` → hub + note petals, no image generated → open a petal → button reads "Generate image" / "Muse Image · inside the Body mask" → click → result + ✓ → Keep → a new item is on the board, selectable, with its own callouts.
3. Open a second dimension on the same image and one on another image → three flowers visible, no overlap (assert bounding boxes via `boundingBox()`), and the first flower's hub position unchanged after opening the others; item positions unchanged.
4. Extract "Detail" → a linked child item appears to the right with its own callouts.
5. Add a note → callouts show a passage part → open `Tone` → petal card button "Rewrite passage" / "Muse Spark · this passage only" → render → changed span marked.
6. Wide screenshot (1600×900 fixture) → UI callouts with boxes (`header`, `primary button`).
- [ ] **Step 1: Write specs** (fail on missing UI if earlier tasks incomplete).
- [ ] **Step 2: Run** `make e2e` → all pass (run twice to catch flakes).
- [ ] **Step 3: Run** `make test && make lint`.
- [ ] **Step 4: Update README "calm board" section** to describe callouts/flowers and the loop (short).
- [ ] **Step 5: Commit** `test(e2e): exploration map flows; docs`
