# Design Language Engine — Implementation Plan (v3: live board, any domain)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A designer builds a live board on an infinite canvas. They add images, videos and links by upload, drop, paste or a Chrome extension (Instagram reels, Pinterest pins, any page). Everything added is parsed. The board itself becomes the source of intelligence: its lens, its recurring signals and its tensions. From any item they can vary one attribute while protecting others and get up to six validated, credited, licensed alternatives. Kept alternatives join the board.

**Architecture:**
- **Engine:** domain-agnostic. Lenses (JSON) declare parts and attributes. Seven attribute kinds (`enum`, `ordinal`, `number`, `boolean`, `color`, `text`, `shape`) each have their own comparator.
- **Backend:** Python FastAPI. One ingestion pipeline normalises every addition (image, video, link, extension capture) into board items. Extraction and SAM grounding run per item. A board-intelligence service keeps the board profile live and pushes it over SSE.
- **Retrieval:** unchanged in principle, now also weighted by the board centroid.
- **Front end:** react-konva infinite canvas, borderless images.
- **Chrome extension (MV3):** puts things on the board with one click.

**Tech Stack:**
- **Backend:** Python 3.12 (uv), FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic + SQLite, `sse-starlette`, `openai` SDK → Meta Model API, `meta-sam-parser`, httpx, `selectolax` (OpenGraph), PyAV (video keyframes), Pillow, NumPy, scikit-image, scikit-learn, OpenCV-headless (contours), transformers + torch (SigLIP 2-B), pytest + respx.
- **Front end:** Vite, React 19.2, TypeScript, TanStack Query, react-konva `~19.2.7`, Vitest, Playwright.
- **Extension:** Chrome MV3, TypeScript, built with Vite.

**Spec:** `docs/superpowers/specs/design-language-engine-vertical-slice.md`, plus the user's amendments of 2026-10-26:
- any domain
- seven attribute kinds and a 20-attribute cap
- a canvas with borderless images
- extension capture of Instagram and Pinterest
- links on the board
- board context
- intelligence comes from the board

**Research:** `reports/Meta models image sources and stack.md`. **Product context:** the "Meta Hackathon: Design Language Engine" doc.

## Decisions

- **Meta interface (confirmed):** `https://api.meta.ai/v1`, Bearer `MODEL_API_KEY`, `openai` SDK.
  - `muse-spark-1.3` (Responses API, `text.format` schemas, ≤50 images, accepts MP4)
  - `sam-3.1` (one noun phrase per call; also video tracking of ≤16 objects)
  - no embeddings endpoint
  - India is allowed; only Muse Image is blocked
- **Two kinds of image, two rights regimes:**
  - **Board items** are what the user brings: uploads, links, extension captures. They are private references for this user. They are stored with full provenance (source URL, creator handle when visible, capture time) and `rights_status: user_supplied`. They are **never** put into the retrieval corpus and never shown to anyone else.
  - **Corpus items** are the licensed retrieval pool (museums CC0, Commons, Openverse BY/BY-SA, gated Pexels, self-captured OSS UI screenshots). Only corpus items can be returned as candidates.
- **Extension capture is user-initiated only.** One click captures one thing the user is looking at. No crawling, no background collection, no bulk "save whole board". Video is captured as frames from the visible tab (`chrome.tabs.captureVisibleTab` + crop to the `<video>` element), not by downloading the file. The demo video uses designer boards captured with consent.
- **Board intelligence** comes from aggregating the parsed attributes of every board item:
  - a lens chosen or proposed from the board
  - **signals**: values shared by most items
  - **tensions**: two competing values
  - **counter-examples**: items the user marked "not this"
  - a board centroid embedding

  These set default protected attributes, feed relevance scoring, and update live as items are added.
- **"Active reference" is gone.** Any item on the board can be the source of a Vary action. Kept candidates become board items (`origin: candidate`, linked to their parent).
- Single user and no auth. The extension pairs with the backend using a one-time token.
- Out of scope for this slice: the ask agent, the language card, checking against the language, and exports. Board signals are the raw material they will use.

## Global Constraints

- Never generate or edit images. Never call `/v1/images/*`. Never use `*-contributor` models.
- No domain names in engine code (`test_domain_agnostic`).
- Accepted inputs:
  - images `jpeg|png|webp|gif(first frame)`, ≤10 MiB, shortest edge ≥256 px
  - videos `mp4|mov|webm`, ≤100 MiB, ≤90 s
  - links `http(s)` only
- Originals are stored unmodified; provenance is never invented. A missing creator stays null.
- Item parse status: `pending | processing | completed | failed`.
- Attribute record: `key, label, category, kind, part, value, confidence, status, source, evidence, enabled`.
- Lens: ≤8 parts, ≤20 attributes.
- Modes:
  - `explore | prefer | avoid` for any kind
  - `nudge {direction: more|less, steps: 1|2}` for `ordinal` and `number` only
  - exactly one target; target ∉ protected (server-enforced)
- Ranking config `rank-2026.10-c`, weights target .35 / preservation .35 / relevance .20 / diversity .10, `validated: false`. Relevance = 0.6·cos(source item) + 0.4·cos(board centroid).
- ≤6 results; never relax constraints; unknown never matches.
- Canvas images render with **no border, no radius, no padding, no shadow**. Selection and status are drawn outside or over the image, never as a frame.
- Errors: `{"error": {"code", "message", "details"?}}`.

## Review Focus

1. **The same image arrives twice** (upload + extension, or a Pinterest pin pasted as a link after being captured). One board item, matched by SHA-256 of the fetched bytes. Pinned in T3.
2. **A link that cannot be unfurled** (Instagram's login wall). The item stays on the board as a link card with "Use the extension to capture this", and the board is not blocked. Pinned in T3.
3. **A video with no usable frames** (black, too short). The item shows `failed: NO_USABLE_FRAMES` and the rest of the board continues. Pinned in T3.
4. **A board whose items span two domains** (watch + interior). The profile reports a mixed board and asks the user to pick a lens. No silent averaging. Pinned in T8.
5. **A user edit made while the board profile recomputes.** The edit wins and the profile recomputes again. Pinned in T8.

---

## File Structure

```
backend/app/
  lenses/{watch,fashion,interior,ui}.json
  domain/      lens.py · attributes.py · kinds.py · variation.py
  db/          models.py · session.py · repos/*.py
  storage/     files.py
  ingest/      validate.py · images.py · video.py · links.py · service.py
  providers/   meta_client · reasoning · segmentation · embedding · reliability · cache
  measure/     palette.py · shape.py · crops.py
  lens_service.py
  extraction/  service.py · merge.py
  board/       profile.py · events.py
  corpus/      sources/* · provenance.py · indexer.py · hashing.py
  retrieval/   config · pool · filters · scores · select
  validation/  comparators.py · validator.py
  runs/ feedback/ api/
backend/scripts/  smoke_meta · import_corpus · index_corpus · seed · embedder_ab
frontend/src/
  canvas/      Canvas.tsx · ItemNode.tsx · VideoNode.tsx · LinkNode.tsx · Lineage.tsx · Selection.tsx · useViewport.ts
  panels/      ContextBar.tsx · AddMenu.tsx · ItemToolbar.tsx · InspectPanel.tsx · VaryPanel.tsx ·
               MaybeStrip.tsx · CandidatePopover.tsx · BoardSignals.tsx · LensReview.tsx · Onboarding.tsx
  api.ts · events.ts · shortcuts.ts
extension/
  manifest.json · src/background.ts · src/content.ts · src/popup.tsx · src/capture.ts · src/pair.ts
```

---

### Task 0: Scaffold and Meta smoke test

**Files:** repo root (`Makefile`, `.gitignore`, `.env.example`, `README.md` stub), `backend/pyproject.toml`, `backend/app/main.py` (FastAPI app with `GET /api/health` → `{"ok": true}`), `backend/app/config.py` (pydantic-settings `Settings` reading every variable in the Environment section), `backend/tests/unit/test_smoke.py`, `backend/scripts/smoke_meta.py`, `frontend/` (Vite React-TS app), `extension/` (empty MV3 skeleton: `manifest.json` + `src/background.ts`, Vite build to `extension/dist`).

**Interfaces — Produces:**
- Make targets: `make dev` (uvicorn :8000 + vite :5173), `make test` (pytest), `make lint` (ruff + mypy for backend; eslint + tsc for frontend and extension), `make e2e` (Playwright), `make seed`, `make ext`, `make smoke`.
- `Settings` fields (names exactly as the Environment section).
- `backend/scripts/smoke_meta.py`: runs these checks against the live API and prints `PASS`/`FAIL`/`SKIP` + latency for each; it never raises; with no `MODEL_API_KEY` every check prints `SKIP`:
  1. `muse-spark-1.3` text call via `openai.OpenAI(base_url=META_BASE_URL, api_key=MODEL_API_KEY).responses.create(...)`
  2. a 10-image Responses call with `text={"format": {"type": "json_schema", "name": "probe", "schema": {...}, "strict": True}}`
  3. `sam-3.1` on one image with input text "watch dial", decoded with `meta_sam_parser`
  4. `GET {META_BASE_URL}/embeddings` → record the status code (expected 404)
  5. Baseten chat completion with model `meta-models/muse-spark-open`, then `meta-models/muse-spark-open-1026` (`max_tokens: 1`; SKIP without `BASETEN_API_KEY`)
  6. latency summary
  7. `sam-3.1` on a 3-second MP4 (`input_video`), confirming video tracking output parses
  - When a check passes, its raw response is saved under `backend/tests/fixtures/meta/` (`spark_text.json`, `spark_schema.json`, `sam_image.txt`, `sam_video.txt`) for later replay tests.

- [ ] **Step 1:** `git` is already initialised by the controller. Run `uv python install 3.12`; `uv init --package backend` (or equivalent layout with `backend/app` as the package); add deps: fastapi, uvicorn[standard], pydantic>=2, pydantic-settings, sqlalchemy>=2, alembic, sse-starlette, openai, meta-sam-parser, httpx, selectolax, av, pillow, numpy, scikit-image, scikit-learn, opencv-python-headless, python-multipart, python-ulid; dev deps pytest, pytest-asyncio, respx, ruff, mypy. Do **not** add torch/transformers yet (Task 4 adds them as an optional extra `embed`).
- [ ] **Step 2:** `npm create vite@latest frontend -- --template react-ts`; pin `react@~19.2`, `react-dom@~19.2`, `react-konva@~19.2.7`, `konva`, `@tanstack/react-query`; dev deps vitest, @testing-library/react, jsdom, @playwright/test.
- [ ] **Step 3:** Write `tests/unit/test_smoke.py`: `test_health` uses FastAPI `TestClient` → `GET /api/health` returns 200 `{"ok": true}`. Run `make test`. Expected: FAIL before main.py exists, then PASS.
- [ ] **Step 4:** Write `smoke_meta.py`. Run it without a key: every check prints SKIP and exit code is 0.
- [ ] **Step 5:** `make lint && make test`. Expected: green. Commit `chore: scaffold backend, frontend, extension; meta smoke script`.

### Task 1: Lens schema, seven attribute kinds, four lenses

**Files:** `app/domain/{lens,attributes,kinds}.py`, `app/errors.py`, `app/lenses/{watch,fashion,interior,ui}.json`; Test: `tests/unit/domain/test_kinds.py`, `test_lens.py`, `test_attributes.py`, `test_domain_agnostic.py`

**Interfaces — Produces:**
- `app/errors.py`: `class AppError(Exception)` with `status: int`, `code: str`, `message: str`, `details: Any = None`; a FastAPI exception handler registered in `main.py` that returns `{"error": {"code", "message", "details"?}}`.
- `PartSpec {id: str (snake_case), sam_prompt: str (1–3 words; must not contain "and", ",", " or ", "not"), grounding: 'sam'|'whole_image' = 'sam'}`.
- `AttributeSpec {key: snake_case, label, category, part: str|None, kind, ...}` with per-kind fields (Pydantic discriminated union on `kind`):

| kind | fields | value stored as |
|---|---|---|
| `enum` | `vocabulary: list[str]|None`, `open_vocabulary: bool = False` (vocabulary required when not open) | string |
| `ordinal` | `scale: list[str]` (ordered, 3–7 unique steps) | string ∈ scale |
| `number` | `unit: str`, `min: float`, `max: float`, `tolerance: float > 0`, `measure: 'model'|'mask_ratio'|'palette_count' = 'model'` | float |
| `boolean` | — | `"true"`/`"false"` |
| `color` | — (measured by code) | colour name + `measured_json {lab, hex}` |
| `text` | `hint: str|None` | string |
| `shape` | `part` required; `experimental: Literal[True]` | descriptor in `measured_json` |

- `LensSpec {id: '<domain>@<n>', domain, label, origin: 'curated'|'proposed'|'edited', parts: list[PartSpec] (≤8), attributes: list[AttributeSpec] (≤20), notes: list[str] = []}`. Validation: keys unique; every `attribute.part` is a declared part id or None; `shape` attributes rejected unless `settings.SHAPE_KIND_ENABLED` (pass the flag in via a validation context or a `validate_lens(spec, shape_enabled: bool)` helper).
- `AttributeRecord {key, label, category, kind, part, value: str|float|bool|None, confidence: float 0..1, status: 'extracted'|'uncertain'|'missing'|'edited'|'confirmed', source: 'model'|'mock'|'user'|'corpus_index'|'measured', source_detail: str, evidence: {kind: 'region'|'cue'|'measurement'|'none', bbox?: [x1,y1,x2,y2] in 0..1, note?: str}, enabled: bool = True, measured: dict|None}`.
- `RELIABLE_CONFIDENCE = 0.7`, `MIN_CONFIDENCE = 0.4`.
- `normalize_model_attribute(raw: ModelAttribute, spec: AttributeSpec, source: str, source_detail: str) -> AttributeRecord`:
  - value outside a closed vocabulary / ordinal scale, number outside min/max, non-boolean for boolean → `value=None, status='missing'` (raw kept only in the event log by the caller);
  - open-vocabulary enum → canonical lower snake_case, kept;
  - `evidence.kind == 'none'` or confidence < 0.4 → `value=None, status='missing'`;
  - 0.4 ≤ confidence < 0.7 → value kept, `status='uncertain'`;
  - ≥ 0.7 with evidence → `status='extracted'`.
- Curated lenses (exact attribute keys; vocabularies are the implementer's reasonable choice unless listed):
  - **watch** — parts: watch case, watch dial, bezel, watch hands, watch strap. Attributes: `case_shape` (enum: round, cushion, tonneau, rectangular, square, octagonal, oval), `case_material` (enum, open), `case_finish` (enum: brushed, polished, brushed_and_polished, bead_blasted, pvd_coated), `dial_color` (color, part watch_dial), `dial_finish` (enum), `bezel_style` (enum), `strap_material` (enum, open), `strap_color` (color, part watch_strap), `markers` (enum), `hands` (enum), `case_diameter_mm` (number, unit mm, 20–55, tol 1.5), `has_date_window` (boolean), `legibility` (ordinal: low, medium, high), `case_silhouette` (shape, part watch_case), `overall_style` (text).
  - **fashion** — parts: garment, sleeve, collar, footwear. Attributes: `silhouette` (enum), `fabric` (enum, open), `pattern` (enum), `primary_color` (color, part garment), `sleeve_length` (ordinal: sleeveless, short, three_quarter, long), `neckline` (enum), `formality` (ordinal: loungewear, casual, smart_casual, business, evening, black_tie), `fit` (ordinal: fitted, regular, relaxed, oversized), `has_pattern` (boolean), `garment_silhouette` (shape, part garment), `era` (text), `occasion` (enum, open).
  - **interior** — parts: sofa, chair, table, lamp, rug, wall. Attributes: `furniture_form` (enum, open), `primary_material` (enum, open), `wood_tone` (ordinal: pale, light, medium, dark, ebony), `wall_color` (color, part wall), `textile` (enum, open), `lighting` (enum), `density` (ordinal: sparse, balanced, layered, maximal), `warmth` (ordinal: cool, neutral, warm), `ceiling_height_feel` (ordinal: low, standard, high, double_height), `has_plants` (boolean), `sofa_profile` (shape, part sofa), `era` (text), `style` (enum, open).
  - **ui** — parts: button, card, navigation bar, heading text, all `grounding: whole_image`. Attributes: `primary_color` (color, part None), `background_tone` (ordinal: dark, dim, neutral, light, white), `corner_radius` (ordinal: sharp, small, medium, large, pill), `density` (ordinal: compact, regular, airy), `type_style` (enum: sans, serif, mono, display), `elevation` (ordinal: flat, subtle, strong), `palette_size` (number, unit colours, 1–12, tol 1, measure palette_count), `has_illustration` (boolean), `iconography` (enum: line, filled, duotone, none), `layout_pattern` (text), `mood` (text).

- [ ] Failing tests:
  - `each kind validates its own fields` (one parametrised case per kind)
  - `enum without vocabulary and not open → invalid`
  - `ordinal outside scale → missing`; `number outside min/max → missing`; `boolean accepts only true/false`
  - `open vocabulary value canonicalised and kept`; `no evidence → missing at 0.95`; `0.55 → uncertain`; `0.82 with region evidence → extracted`
  - `shape rejected when flag off, accepted when on`
  - `lens with 21 attributes rejected`; `attribute with undeclared part rejected`; `sam_prompt containing "and" rejected`
  - `four curated lenses validate (with shape flag on); with flag off they validate after shape attributes are filtered by the loader`
  - `test_domain_agnostic`: no `.py` file under `app/` except within `app/lenses/` contains the words watch, fashion, interior, dial, sofa (case-insensitive)
- Implement, pass, commit `feat(domain): seven attribute kinds, lens schema, four curated lenses`.

### Task 2: Persistence (boards, items, positions, lineage)

**Files:** `app/db/{models,session}.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_init.py`, `app/db/repos/{boards,items,attributes,lenses,masks,corpus,runs,decisions,profiles,cache,idempotency,tokens}.py`; Test: `tests/integration/db/test_repos.py`; helper `tests/conftest.py` with a `session` fixture (in-memory SQLite with migrations applied).

**Interfaces — Produces:** SQLAlchemy 2 models; ids are prefixed ULIDs (`brd_ itm_ frm_ att_ evt_ lens_ cx_ run_ cand_ val_ dec_`); timestamps ISO-8601 UTC set by the server; SQLite with `PRAGMA foreign_keys=ON` and WAL.
- `boards(id, title, context, domain?, lens_id?, created_at, updated_at)`.
- `board_items(id, board_id, kind 'image'|'video'|'link', origin 'upload'|'drop'|'paste'|'link'|'extension'|'candidate'|'seed', sha256?, storage_path?, thumb_path?, mime?, width?, height?, original_filename?, source_url?, page_url?, page_title?, creator_handle?, captured_at, rights_status 'user_supplied'|'licensed', corpus_item_id?, parent_item_id?, parse_status 'pending'|'pending_lens'|'processing'|'completed'|'failed', parse_error_code?, parse_attempts, role 'reference'|'counter_example', x, y, w, h, z, removed_at?, created_at)`. Partial unique index `(board_id, sha256) WHERE removed_at IS NULL AND sha256 IS NOT NULL`. Check: `rights_status='licensed'` ⇔ `corpus_item_id IS NOT NULL`.
- `item_frames(id, item_id, t_ms, sha256, storage_path, chosen bool)`.
- `item_attributes(id, item_id, key, label, category, kind, part, value_json, confidence, status, source, source_detail, evidence_json, enabled, model_value_json?, model_confidence?, measured_json?, updated_at)`; unique `(item_id, key)`.
- `attribute_events(id, item_id, key, actor 'user'|'model', action 'extracted'|'model_suppressed'|'edited'|'confirmed'|'disabled'|'enabled', before_json, after_json, created_at)` — append-only.
- `lenses(id, domain, version, origin, status 'proposed'|'confirmed', spec_json, created_at)` — immutable; unique `(domain, version)` per board scope via `board_id?` column.
- `part_masks(image_sha256, sam_prompt, found, bbox_json?, mask_path?, score?, provider, created_at)`; PK `(image_sha256, sam_prompt)`.
- `corpus_items(id, domain, source, source_id, landing_url, image_url, local_path?, creator_name?, license_code, license_url?, attribution_text, fetched_at, sha256?, dhash?, width?, height?, embedding_row?, indexing_status 'pending'|'indexed'|'failed', provenance_status 'valid'|'invalid', provenance_issue?)`.
- `corpus_attributes(item_id, key, value_json, confidence, source, evidence_json, measured_json?)`; PK `(item_id, key)`.
- `board_profiles(board_id, version, profile_json, computed_at)`; PK `(board_id, version)`.
- `variation_runs(id, board_id, source_item_id, lens_id, target_key, mode, target_values_json, nudge_json?, protected_keys_json, source_snapshot_json, board_profile_version, ranking_version, ranking_config_json, validator_version, providers_json, status 'queued'|'retrieving'|'validating'|'completed'|'failed', progress_json?, summary_json?, error_code?, idempotency_key UNIQUE, created_at, completed_at?)`.
- `run_candidates(id, run_id, corpus_item_id, state 'retrieved'|'excluded'|'validating'|'validated'|'uncertain'|'rejected', excluded_reason?, excluded_detail?, scores_json?, rank?, observed_target_json?)`; unique `(run_id, corpus_item_id)`.
- `validation_results(id, run_candidate_id, check, attribute_key?, verdict, reason, evidence_json, validator_version)`.
- `decisions(id, board_id, run_id, run_candidate_id, corpus_item_id, decision 'keep'|'reject', reason_code?, note?, item_id?, created_at)` — append-only.
- `model_cache(key PK, provider, model, prompt_version, response_json, created_at)`; `idempotency_keys(key PK, route, request_hash, status_code, response_json, created_at)`; `extension_tokens(token_hash PK, created_at, last_used_at?)`.
- Repos: module-level functions taking `session` first (e.g. `items.create(session, **fields) -> BoardItem`, `items.update_position(session, id, x, y, w, h, z)`, `decisions.append(session, ...)`, `decisions.history(session, run_candidate_id)` newest-first, `profiles.save(session, board_id, profile) -> version`, `profiles.latest(session, board_id)`). Append-only repos (`attribute_events`, `decisions`) expose no update/delete functions.

- [ ] Failing tests:
  - `migration applies to an empty db`
  - `duplicate active sha256 on a board rejected; allowed after soft delete; allowed on another board`
  - `item positions persist and update`
  - `item with parent_item_id links to parent`
  - `licensed item requires corpus_item_id; user_supplied must not have one`
  - `lens versions immutable: saving an edit creates version 2, version 1 unchanged`
  - `attribute_events and decisions repos expose no update/delete`
  - `decision history newest-first`
  - `board_profiles keeps history; latest returns highest version`
- Implement, pass, commit `feat(db): boards, items, lineage, profiles, runs schema and repos`.

### Task 3: Ingestion (upload, drop, paste, video, links)

**Files:** `app/ingest/*.py`, `app/api/items.py`; Test: `tests/unit/ingest/test_validate.py`, `test_video.py`, `test_links.py`, `tests/integration/api/test_items.py`

**Interfaces — Produces:**
- `POST /api/boards/{id}/items`, accepting one of:
  - multipart `files[]` (1–50 per request; each validated independently; partial success returns per-file results)
  - JSON `{url}`
  - JSON `{capture: {image_b64 | frames_b64[], source_url, page_url, page_title, creator_handle?, kind}}` (extension)
  - Optional `{x, y}` drop point; otherwise the server auto-places to the right of existing items.
- `ingest_image(bytes, meta) -> BoardItem`: magic-byte check, decode, SHA-256 dedupe, store, thumbnail
- `ingest_video(bytes, meta)`: PyAV decode; keyframes = scene-change frames, max 6, at least 1 s apart, dropping near-black and near-duplicate (dHash ≤ 6) frames. The middle usable frame is `chosen`. No usable frame → `NO_USABLE_FRAMES`.
- `ingest_link(url)`:
  1. Fetch with a 5 s timeout, max 2 MiB, User-Agent `DesignLanguageEngine/0.1 (+contact)`.
  2. Parse `og:image`, `og:video`, `og:title`, `twitter:image`, `<link rel=image_src>`.
  3. If an image is found, download it and ingest it as an image with `origin: link`.
  4. If not (login walls such as Instagram), save a `kind: link` item with `parse_status: failed`, `parse_error_code: LINK_NEEDS_EXTENSION`.
  5. Never follow more than 3 redirects; never fetch private IP ranges (SSRF guard).
- Every new item enqueues parsing (T7) and emits an `item.added` SSE event (T8).
- `PATCH /api/items/{id}` (`x,y,w,h,z`, `role`, `chosen_frame_id`); `DELETE /api/items/{id}` (soft)

- [ ] Failing tests:
  - `50-file upload with one bad file → 49 ok + 1 error`
  - `same bytes via upload and capture → one item`
  - `mp4 yields 1–6 frames, middle chosen`
  - `black video → NO_USABLE_FRAMES`
  - `og:image page → image item with page_url provenance`
  - `instagram-like login wall → link item LINK_NEEDS_EXTENSION`
  - `url to 10.0.0.1 rejected SSRF_BLOCKED`
  - `drop point respected`
  - Commit `feat(ingest): images, video keyframes, link unfurl`.

### Task 4: Providers (Meta client, SAM, embeddings, reliability, cache, mocks)

**Files:** `app/providers/{meta_client,reasoning,segmentation,embedding,reliability,cache}.py`; Test: `tests/unit/providers/test_reliability.py`, `test_meta_client.py` (respx), `test_sam_decode.py`, `tests/integration/providers/test_cache.py`; fixtures in `tests/fixtures/meta/` (use the files recorded by Task 0 if present; otherwise hand-write minimal fixtures that match the documented shapes below and say so in the report).

**Interfaces — Produces:**
- `meta_client.get_client(settings) -> openai.OpenAI` with `base_url=META_BASE_URL`, `api_key=MODEL_API_KEY`.
- `ReasoningProvider` (Protocol): attributes `id: str`, `model: str`, `is_mock: bool`; methods
  - `extract(images: list[bytes], lens: LensSpec, context: str) -> list[ModelAttribute]` — one `responses.create` call, `text.format` json_schema built from the lens (Task 7 owns the schema builder; here accept a prebuilt `schema: dict` parameter: `extract(images, schema, prompt) -> dict`), `reasoning={"effort": "low"}`, `store=False`; ≤6 images (video frames) per call.
  - `propose_lens(images: list[bytes], context: str, schema: dict) -> dict` — ≤20 images.
  - `verify(images: list[bytes], schema: dict, prompt: str) -> dict` — streamed (`stream=True`), raises `ModelError("TOO_MANY_IMAGES")` before calling when `len(images) > 50`.
- `MuseSparkProvider(client, model)`; `MuseSparkOpenProvider(base_url="https://inference.baseten.co/v1", api_key, model)` uses chat completions, parses JSON from the text itself and retries once on parse failure; `MockReasoningProvider` returns deterministic output derived from SHA-256 of the inputs and the schema (every enum/ordinal field picks a value by hash; confidences 0.45–0.65 unless a fixture map supplies ground truth).
- `SegmentationProvider` (Protocol): `id`, `is_mock`; `localize(image: bytes, sha256: str, noun: str) -> SegResult` where `SegResult = {found: bool, instances: list[{bbox: (x1,y1,x2,y2), mask: np.ndarray[bool], score: float|None}]}`; `track(video: bytes, noun: str) -> list[SegResult]` (per frame).
  - `Sam31Provider` sends `model="sam-3.1"`, one `input_text` (the noun) + one `input_image` (base64 data URL) or `input_video`, `metadata={"include_confidence": "true", "mask_encoding": "one_bit"}`, decodes `output_text` with `meta_sam_parser` to rasters. Empty `output_text` → `found=False`.
  - `MockSegmentationProvider` returns one centred box covering the middle 60% of the image with a matching mask.
- `Embedder` (Protocol): `id`, `dim`; `embed_images(list[bytes]) -> np.ndarray[n, dim]` (L2-normalised), `embed_text(list[str])`. `SigLIP2Embedder("google/siglip2-base-patch16-256")` and `PECoreEmbedder` live behind an optional extra `embed` (torch, transformers) and are imported lazily; `MockEmbedder` = 64-d RGB histogram (4×4×4 bins of a 64×64 downsample), L2-normalised.
- `reliability.ModelError(code: str, retry_after: float|None)`; codes: `MODEL_TIMEOUT`, `MODEL_UNAVAILABLE`, `MODEL_RATE_LIMITED`, `MODEL_INVALID_RESPONSE`, `GATEWAY_TIMEOUT`, `PAYLOAD_TOO_LARGE`, `BILLING_NOT_CONFIGURED`, `TOO_MANY_IMAGES`, `PROVIDER_MISCONFIGURED`.
  - HTTP mapping: 429 → RATE_LIMITED (read `Retry-After`), 5xx except 504 → UNAVAILABLE, 504 → GATEWAY_TIMEOUT, 413 → PAYLOAD_TOO_LARGE, 402 → BILLING_NOT_CONFIGURED, 400 schema errors → INVALID_RESPONSE, client timeout → TIMEOUT.
- `with_timeout(fn, seconds)`; `with_retry(fn, max_retries=MODEL_MAX_RETRIES, base_delay=0.25)` retries only TIMEOUT, UNAVAILABLE, RATE_LIMITED (sleeping `retry_after` when given, else exponential); never retries INVALID_RESPONSE, GATEWAY_TIMEOUT, BILLING_NOT_CONFIGURED.
- `cache.cached_call(session, key_parts: list, schema: type[BaseModel] | None, fn) -> Any`: key = sha256 of canonical JSON of `key_parts`; stores JSON in `model_cache`; on read re-validates with `schema` and refetches if invalid.
- `get_reasoning(settings)`, `get_segmentation(settings)`, `get_embedder(settings)`: select by `REASONING_PROVIDER`, `SEGMENTATION_PROVIDER`, `EMBEDDER`; a live provider with its key missing raises `ModelError("PROVIDER_MISCONFIGURED")` (no silent fallback). Any model id ending in `-contributor` raises `PROVIDER_MISCONFIGURED`.

- [ ] Failing tests:
  - `extract sends text.format json_schema, effort low, store false` (respx asserts the request body)
  - `extract parses a recorded Responses payload (output[] → message → output_text JSON)`
  - `400 schema error → MODEL_INVALID_RESPONSE, not retried`
  - `429 with Retry-After: 1 is retried once then succeeds`
  - `504 → GATEWAY_TIMEOUT, no retry`
  - `verify with 51 images raises TOO_MANY_IMAGES without an HTTP call`
  - `sam fixture decodes to ≥1 instance with bbox inside image bounds`
  - `empty sam output → found False`
  - `mock providers set is_mock True and are deterministic`
  - `cached_call invokes fn once for the same key; refetches on invalid cached JSON`
  - `contributor model id raises PROVIDER_MISCONFIGURED`
  - `MockEmbedder output is L2-normalised, dim 64`
- Implement, pass, commit `feat(providers): Meta client, SAM decode, embedders, reliability, cache, mocks`.

### Task 5: Measurement (colour, number, shape)

**Files:** `app/measure/{palette,shape,crops}.py`; Test: `tests/unit/measure/*`

**Interfaces — Produces:**
- `masked_palette(image: np.ndarray, mask: np.ndarray | None, k=5) -> list[{lab: (L,a,b), hex, share}]` (k-means in CIELAB on masked pixels, all pixels when mask is None); `dominant_lab(palette)`; `delta_e(a, b) -> float` (CIEDE2000 via scikit-image); `nearest_color_name(lab) -> str` (fixed table of ~30 named colours); `crop_part(image, mask, pad=0.05) -> bytes` (outside-mask pixels painted 50% grey)
- `palette_count(image, mask, min_share=0.05) -> int`
- `mask_ratio(mask_a, mask_b) -> float`: e.g. part area relative to the whole object
- `shape_descriptor(mask) -> {hu: [7 floats], contour: 64-point normalised polyline}`
- `shape_similarity(a, b) -> float in 0..1`: combines Hu-moment distance (log-scaled) with the IoU of the aligned contour (centred, scale-normalised, best of 8 rotations)
- `SHAPE_SAME_MIN = 0.85`, `SHAPE_DIFFERENT_MAX = 0.60` (experimental)

- [ ] Failing tests:
  - `circle vs circle similarity ≥ .95`
  - `circle vs square ≤ .6`
  - `cushion vs round between`
  - `palette_count of 3-colour flat image = 3`
  - `similarity invariant to scale and 90° rotation`
  - Commit.

### Task 6: Lens service (board-driven)

**Files:** `app/lens_service.py`, `app/api/lenses.py`; Test: `tests/integration/test_lens_service.py`

**Interfaces — Consumes:** T1 `LensSpec`, T2 repos (`lenses`, `boards`, `board_items`), T4 providers. **Produces:**
- `curated_lens(domain: str) -> LensSpec | None` (loads `app/lenses/<domain>.json`).
- `ensure_board_lens(session, board_id) -> LensSpec | None`:
  - board `domain` set and curated lens exists → attach it (store as a `lenses` row, origin `curated`) and return it;
  - otherwise, when the board has ≥5 items with `parse_status in ('completed','pending_lens')` and no lens: call `propose_lens`, return `None` meanwhile.
- `propose_lens(session, board_id) -> LensSpec`: samples ≤20 board items maximising embedding diversity (greedy farthest-point from the centroid), calls `ReasoningProvider.propose_lens` with a schema derived from `LensSpec` (via Pydantic `model_json_schema()`), validates the result as `LensSpec` with `origin='proposed'`, then `prune_parts`, stores it as a new `lenses` row with `status='proposed'`, emits `lens.proposed`.
- `prune_parts(lens, images: list[bytes]) -> LensSpec`: runs `localize` for each part on ≤10 images; a part found in <50% → `grounding='whole_image'` and a line in `lens.notes`.
- `confirm_lens(session, board_id, spec: LensSpec | None)`: confirm as-is, or save the edited spec as a new version with origin `edited`; set `boards.lens_id`; mark every item with `parse_status='pending_lens'` as `pending` and enqueue parsing.
- `domain_votes(items) -> dict[str, float]`: delegated to T8; here, if votes show two domains within 40/60 → `ensure_board_lens` raises `AppError(409, "LENS_AMBIGUOUS", details={"candidates": [d1, d2]})`.
- API: `POST /api/boards/{id}/lens:propose`, `PUT /api/boards/{id}/lens` (body: optional LensSpec), `GET /api/lenses/{id}`.
- Items added before a lens exists get embedding + palette only and `parse_status='pending_lens'`.

- [ ] Failing tests: `curated lens attached when domain matches`; `no proposal under 5 items`; `proposal sampled from board items, max 20`; `proposed lens validates as LensSpec with origin proposed`; `low-hit part falls back to whole_image with a note`; `confirm with edits creates version 2; version 1 still readable`; `pending_lens items re-queued after confirmation`; `mixed-domain board → 409 LENS_AMBIGUOUS`. Implement, pass, commit `feat(lens): board-driven lens selection and proposal`.

### Task 7: Item parsing (extraction)

**Files:** `app/extraction/{schema,service,merge}.py`, `app/api/attributes.py`; Test: `tests/unit/extraction/test_schema.py`, `test_merge.py`, `tests/integration/test_parsing.py`

**Interfaces — Consumes:** T1, T2, T4, T5, T6. **Produces:**
- `build_extraction_schema(lens) -> dict`: JSON schema with one property per non-measured attribute: enum/ordinal → `{"type": ["string","null"], "enum": [...values, null]}` (open-vocabulary enum → plain string|null); number → `{"type": ["number","null"], "minimum", "maximum"}`; boolean → `{"type": ["boolean","null"]}`; text → string|null; each wrapped as `{value, confidence (0..1), evidence {kind: region|cue|none, bbox?, note?}}`.
- `parse_item(session, item_id)`:
  1. compare-and-set `parse_status` `pending|failed|completed → processing` in one UPDATE; 0 rows → `AppError(409, "PARSE_IN_PROGRESS")`.
  2. image = the item image, or the chosen frame for video.
  3. SAM `localize` per lens part with `grounding='sam'` (cached in `part_masks` by `(sha256, sam_prompt)`).
  4. Measure: `color` → `masked_palette` on the part mask (whole image if `whole_image`) → nearest named colour + `measured_json {lab, hex}`, `source='measured'`; `number` with `measure='mask_ratio'|'palette_count'` → T5 functions; `shape` (flag on) → `shape_descriptor`.
  5. One `ReasoningProvider.extract` call with `build_extraction_schema(lens)`, the context text and the image; via `cached_call` keyed on (provider, model, prompt_version `item-extract-v1`, lens_id, image sha256, context hash).
  6. `normalize_model_attribute` per attribute (T1), then `merge_extraction`, then `parse_status='completed'` (or `failed` + `parse_error_code` from `ModelError.code`). Attributes are never deleted on failure.
  7. Emit `item.parsed` / `item.failed` and request a profile recompute (T8 `request_recompute(board_id)`; until T8 exists, call a no-op hook defined here).
- `merge_extraction(existing, incoming) -> (rows, events)`: rows with status `edited`/`confirmed` or user-set `enabled=False` keep value/status/enabled; incoming value goes to `model_value`/`model_confidence` with a `model_suppressed` event; other rows are replaced with an `extracted` event.
- API: `GET /api/items/{id}/attributes` → `{parse_status, lens, provider:{id, model, is_mock}, attributes}`; `PATCH /api/items/{id}/attributes/{key}` `{value?, action?: confirm|disable|enable}` validated per kind against the lens (bad value → 400 `INVALID_ATTRIBUTE_VALUE`), appends an `attribute_events` row with before/after; `GET …/attributes/{key}/history`; `POST /api/items/{id}/parse` (retry).

- [ ] Failing tests: `schema: ordinal is enum of scale + null`; `schema: number has min/max`; `ordinal extracted as scale value`; `number outside range → missing`; `boolean without evidence → missing`; `colour comes from measurement not model`; `edited value survives re-parse`; `disabled stays disabled`; `timeout → failed, prior attributes kept`; `invalid response → failed MODEL_INVALID_RESPONSE`; `retry does not duplicate rows`; `concurrent parse → 409`; `edit during processing survives completion`; `video item parsed from chosen frame; changing chosen frame re-parses`; `same service parses a watch board item and a ui board item with their own lenses`. Implement, pass, commit `feat(parsing): lens-driven item parsing with edit-preserving merge`.

### Task 8: Board intelligence and live events

**Files:** `app/board/profile.py`, `app/board/events.py`, `app/api/boards.py`; Test: `tests/unit/board/test_profile.py`, `tests/integration/test_events.py`

**Interfaces — Produces:**
- `compute_profile(items, attrs, lens) -> BoardProfile`:
  - Per attribute: `n_known`, `distribution`, `modal_value`, `consistency` = modal share among reliable values.
    - enum / ordinal / boolean: value counts
    - number: median ± IQR
    - color: Lab k-means over item colours (k ≤ 3), with clusters as values
    - shape: medoid
    - text: not aggregated; listed only
  - `signals`: attributes with `n_known ≥ 3` and `consistency ≥ 0.6`, sorted by consistency
  - `tensions`: attributes whose top two values each hold ≥ 30%
  - `counter_signals`: values that appear mostly on `counter_example` items
  - `centroid`: the mean L2-normalised embedding of reference items
  - `domain_votes`: per item, which curated lens it fits best (by embedding against lens prototypes); `mixed: true` when the top two are within 40/60
- Recomputed after every item completes, edit, role change or removal. Debounced to 1 s per board. Versioned.
- `GET /api/boards/{id}/events` (SSE) emits `item.added`, `item.parsed`, `item.failed`, `profile.updated`, `lens.proposed`, `run.progress`, `run.completed`
- `GET /api/boards/{id}/profile`
- How the profile drives behaviour:
  - `propose_protected(item, target)` orders the chips by signal strength and marks board signals.
  - Relevance uses the centroid.
  - Avoid mode pre-fills `counter_signals`.

- [ ] Failing tests:
  - `3 of 4 items brushed → signal`
  - `2 blue 2 green → tension`
  - `counter_example values become counter_signals`
  - `mixed watch+interior → mixed true`
  - `edit triggers recompute and newer version`
  - `SSE stream delivers item.parsed then profile.updated in order`
  - Commit `feat(board): live board profile and SSE`.

### Task 9: Corpus importers, provenance, indexer, seed

**Files:** `app/corpus/sources/{commons,openverse,met,smithsonian,aic,rijks,pexels,self_capture}.py`, `app/corpus/{provenance,indexer,hashing}.py`, `scripts/{import_corpus,index_corpus,seed}.py`, `corpus/manifests/<domain>.jsonl`, `tests/fixtures/corpus/` (small committed fixture set: ~24 images with a manifest; use CC0/public-domain images fetched once via the Met or Smithsonian sources, or generated solid-colour test images clearly labelled `license_code: "CC0-1.0", source: "test_fixture"` if network is unavailable — say which in the report); Test: `tests/unit/corpus/test_provenance.py`, `test_sources.py` (respx), `tests/integration/test_indexer.py`

**Interfaces — Produces:**
- `Source` protocol: `name`; `search(query: str, limit: int) -> Iterator[ManifestItem]` using official APIs or bulk files only (never HTML scraping).
- `ManifestItem {id: 'cx_<source>_<source_id>', domain, source, source_id, landing_url, image_url, creator_name?, license_code, license_url?, attribution_text, fetched_at}`.
- Per-source rules:
  - `commons`: MediaWiki API `prop=imageinfo&iiprop=url|extmetadata|size`; User-Agent `DesignLanguageEngine/0.1 (contact: $CONTACT_EMAIL)`; ≤200 req/min; licence from `LicenseShortName`/`LicenseUrl`; `Artist` HTML stripped; drop ND and NC licences.
  - `openverse`: `api.openverse.org/v1/images/?license=by,by-sa,cc0,pdm`; use the returned `attribution`.
  - `met`: `collectionapi.metmuseum.org/public/collection/v1.1/search` then per-object fetch; keep only `isPublicDomain == true` with non-empty `primaryImage`; 0.4 s between calls.
  - `smithsonian`: line-delimited JSON from the public S3 bucket (e.g. CHNDM unit); keep media with `usage.access == "CC0"`.
  - `aic`: POST search; keep `is_public_domain`.
  - `rijks`: `data.rijksmuseum.nl` search; licence per object.
  - `pexels`: yields nothing unless `PEXELS_ENABLED=1`; ≤300 items; `license_code: "Pexels"`; credit "Photo by <name> on Pexels".
  - `self_capture`: reads a hand-written manifest; `license_code` = the app's SPDX id.
- `LICENSE_ALLOWLIST = {"CC0-1.0","PDM-1.0","CC-BY-2.0","CC-BY-2.5","CC-BY-3.0","CC-BY-4.0","CC-BY-SA-2.0","CC-BY-SA-3.0","CC-BY-SA-4.0","Pexels","MIT","Apache-2.0","BSD-3-Clause","GPL-3.0-only"}`.
- `check_provenance(item) -> ("valid", None) | ("invalid", "MISSING_SOURCE"|"LICENSE_NOT_ALLOWED"|"MISSING_CREATOR")` — BY/BY-SA require `creator_name`.
- `hashing.sha256(bytes)`, `hashing.dhash(bytes) -> str (16 hex)`, `hashing.hamming(a, b) -> int`.
- `index_corpus(session, domain, manifest_path)`: per item download image (or read bulk file), compute sha256/dHash/size, `part_masks` via SAM for the domain's curated lens, palettes/numbers/shapes (T5), `corpus_attributes` via `extract` (cached), embedding appended to `data/embeddings.npy` with `embedding_row`; idempotent (upsert by id); missing image → `indexing_status='failed'`; `provenance_status` from `check_provenance`.
- `seed()`: four demo boards (watch, fashion, interior, ui), each with context text and 8–12 items created **from corpus items** (`origin: 'candidate'`-like seed origin `seed`, `rights_status: licensed`, `corpus_item_id` set), positioned in a loose grid.
- Target sizes: watch 300–500, fashion ~150, interior ~150, ui ~200 (self-captured). The tests use the fixture set only.

- [ ] Failing tests: `commons NC licence dropped`; `commons Artist HTML stripped`; `met isPublicDomain false skipped`; `pexels yields nothing unless enabled`; `BY without creator invalid`; `dHash of resized copy within 6`; `indexer idempotent (row counts equal after two runs)`; `missing image → failed`; `fixture corpus indexes with mock providers in < 10 s`; `seed creates four boards with 8–12 licensed items each`. Implement, pass, commit `feat(corpus): licensed importers, provenance, indexer, seed`.

### Task 10: Variation request and invariants

**Files:** `app/domain/variation.py`; Test: `tests/unit/domain/test_variation.py`

**Interfaces — Produces:**
- `VariationRequest {source_item_id, target_key, mode: 'explore'|'prefer'|'avoid'|'nudge', target_values: list[str], protected_keys: list[str], nudge: {direction: 'more'|'less', steps: 1|2} | None}`.
- `validate_variation(req, item, attrs, lens) -> VariationSpec`, raising `AppError(422, code)`:
  - `UNKNOWN_ATTRIBUTE` — target or protected key not in the board's lens
  - `TARGET_PROTECTED_CONFLICT` — target ∈ protected
  - `DUPLICATE_PROTECTED_KEY`
  - `TARGET_DISABLED` / `PROTECTED_DISABLED`
  - `PROTECTED_VALUE_UNKNOWN` — a protected attribute has value null
  - `TARGET_VALUES_REQUIRED` — prefer/avoid with empty values
  - `TARGET_VALUES_NOT_ALLOWED` — explore/nudge with values
  - `TARGET_VALUE_INVALID` — value outside the vocabulary/scale/range (colour values must be known colour names)
  - `PREFER_EQUALS_CURRENT` — prefer values == [current value]
  - `EXPLORE_NEEDS_KNOWN_TARGET`
  - `NUDGE_NOT_SUPPORTED` — nudge on a kind other than ordinal/number
  - `NUDGE_NEEDS_KNOWN_TARGET`
  - `NUDGE_OUT_OF_RANGE` — ordinal index ± steps outside the scale, or number outside min/max
  - `NUDGE_PARAMS_REQUIRED` — nudge without `nudge`, or `nudge` given for another mode
  - `SOURCE_IS_COUNTER_EXAMPLE`
- `propose_protected(attrs, target_key, profile: BoardProfile | None) -> list[{key, is_board_signal: bool, strength: float}]`: every enabled attribute with a known value except the target, ordered by board-signal consistency (signals first), then lens order.

- [ ] Failing tests: one per code above; `empty protected set is valid`; `keys validated against the board's lens`; `propose_protected orders signals first and excludes target, disabled, unknown`. Implement, pass, commit `feat(variation): request invariants incl. nudge`.

### Task 11: Pool, exclusions, filters

**Files:** `app/retrieval/{config,pool,filters}.py`, `app/validation/comparators.py` (created here, extended in T13); Test: `tests/unit/retrieval/test_filters.py`, `tests/unit/validation/test_comparators.py`, `tests/integration/test_pool.py`

**Interfaces — Produces:**
- `RANKING_CONFIG = {"version": "rank-2026.10-c", "validated": False, "weights": {"target": .35, "preservation": .35, "relevance": .20, "diversity": .10}, "relevance_mix": {"source_item": .6, "board_centroid": .4}, "reliable_confidence": .7, "pool_size": 200, "shortlist_size": 16, "result_size": 6, "duplicate_dhash_distance": 6, "color_same_max": 10.0, "color_different_min": 20.0, "shape_same_min": .85, "shape_different_max": .60}`.
- `compare(spec: AttributeSpec, a: AttrValue, b: AttrValue, cfg) -> 'same'|'different'|'unknown'`:
  - enum/boolean: both confidence ≥ 0.7 and equal → same; both ≥ 0.7 and unequal → different; else unknown
  - ordinal: both ≥ 0.7: same index → same, |Δindex| ≥ 1 → different; else unknown
  - number: |Δ| ≤ tol → same; |Δ| > 2·tol → different; else unknown (missing → unknown)
  - color: ΔE2000 of measured Lab ≤ 10 → same; ≥ 20 → different; else unknown (no measurement → unknown)
  - shape: similarity ≥ .85 → same; ≤ .60 → different; else unknown
  - text: always unknown
- `build_pool(session, board, source_vec, centroid_vec, cfg) -> list[PoolItem]`: rows of `embeddings.npy` whose corpus item has `domain == board.domain` and `indexing_status == 'indexed'`; relevance = 0.6·cos(source) + 0.4·cos(centroid) (centroid missing → source only); top `pool_size`; ties by id. Board items are never candidates (they are not corpus items).
- `apply_exclusions(pool, spec, source_item, cfg) -> (kept, excluded[{item, reason, detail}])`, in order: `source` (same sha256 or same corpus_item_id as the source item), `unusable` (indexing failed, file missing, shortest edge < 256), `provenance` (invalid), `duplicate` (dHash ≤ 6 to source or a higher-relevance kept item), `hard_constraint` (any protected `compare` == different), `avoided_value` (avoid mode, target compare == same as an avoided value), `no_target_change` (explore mode, target compare == same as source). `detail` names the attribute and both values.

- [ ] Failing tests: one per compare row (incl. `colour ΔE 14 → unknown`, `number within tol → same`, `shape .7 → unknown`, `text → unknown`); `pool restricted to board domain`; `board items never in pool`; `excludes source by sha256`; `excludes resized copy as duplicate`; `missing file → unusable`; `invalid licence → provenance`; `reliable ordinal protected mismatch → hard_constraint`; `unknown protected not excluded`. Implement, pass, commit `feat(retrieval): domain pool, comparators, exclusions`.

### Task 12: Scores and selection

**Files:** `app/retrieval/{scores,select}.py`; Test: `tests/unit/retrieval/test_scores.py`, `test_select.py`

**Interfaces — Produces:**
- `Scores {target, preservation, relevance, diversity, total}`, all 0..1.
- `target_score(spec, source_attr, cand_attr, cfg)`:
  - explore: compare(source, cand) == different → 1; unknown with a value → 0.5·confidence (colour: 0.5·(ΔE−10)/10 in the 10–20 band); missing → 0
  - prefer: cand same as any preferred value → 1; unknown → 0.5·confidence; else 0
  - avoid: cand different from every avoided value → 1; unknown → 0.5·confidence; missing → 0
  - nudge: target index/value = source ± steps (direction) → 1; one step further in the same direction → 0.5; otherwise 0 (number: "step" = 2·tol)
- `preservation_score(spec, source_attrs, cand_attrs, cfg)`: mean over protected keys of {same: 1, unknown with value: 0.5·confidence, missing: 0}; empty protected → 1.
- `relevance` = the pool relevance from T11 mapped to 0..1 via `(cos + 1) / 2`.
- `pair_similarity(a, b, spec) = 0.5·cos(emb) + 0.5·[target compare == same]`.
- `shortlist(cands, cfg)`: top `shortlist_size` by total with diversity = 1.
- `select_diverse(cands, cfg, k)`: greedy; diversity = 1 − max pair_similarity to already-selected (1 for the first); total = Σ weight·score; tie → higher relevance → lower id; returns ≤ k with `rank`.

- [ ] Failing tests: `weights sum to 1`; `explore: missing target scores 0`; `preservation: unknown protected scores 0.5·conf, missing 0, never 1`; `empty protected → 1`; `A, C, B ordering` (A blue rel .90, B blue rel .89 with cos(A,B)=.98, C green rel .80 with cos(A,C)=.85; all target=preservation=1; expect A, C, B); `nudge more from regular prefers airy (1) over compact (0)`; `centroid relevance changes the order of two otherwise equal candidates`; `deterministic`; `≤ k`. Implement, pass, commit `feat(retrieval): scores and diversity selection`.

### Task 13: Validator

**Files:** `app/validation/{comparators,validator}.py`; Test: `tests/unit/validation/test_validator.py`

**Interfaces — Produces:**
- `VALIDATOR_VERSION = "val-3"`.
- `CheckResult {check: 'target'|'protected'|'duplicate'|'provenance', attribute_key?, verdict: 'pass'|'fail'|'uncertain', reason: str, evidence: {source: 'corpus_index'|'measured'|'verify'|'segmentation', confidence?, values?}}`.
- `validate_shortlist(spec, source_item, cands, providers, cfg) -> dict[cand_id, {overall: 'validated'|'uncertain'|'rejected', checks: list[CheckResult], observed_target_value}]`:
  1. provenance invalid → fail; duplicate → fail.
  2. target and each protected key via `compare` (T11) mapped to the mode: target pass when the mode condition holds (explore different; prefer same as a preferred value; avoid different from all avoided; nudge exactly ± steps in the right direction), fail when reliably violated, else uncertain. Protected: same → pass, different → fail, unknown → uncertain.
  3. One streamed `verify` call per ≤8 candidates (plus the source image; ≤50 images total) for every check still uncertain and every `text` check. The prompt shows source and candidate part crops (T5 `crop_part`) and asks per check `same|different|cannot_tell` (+ for ordinal: `more|less|same` with steps) with evidence and confidence. Only answers with confidence ≥ 0.7 resolve a check; `cannot_tell` stays uncertain.
  4. SAM visibility: if the candidate's part for a check has `found=False`, that check becomes uncertain with reason "<part> not visible". A found mask never turns uncertain into pass.
  5. A verify error → affected checks uncertain with reason `verification unavailable (<code>)`.
  6. overall: any fail → rejected; else any uncertain → uncertain; else validated.
- Reasons name attribute, expected and observed values: colours show both hex values and ΔE; ordinal shows "regular → airy (+1)"; shape shows the similarity score.

- [ ] Failing tests: `validated only when all pass`; `mask found does not upgrade uncertain`; `part not found → uncertain`; `text resolved only via verify`; `verify batches ≤8 candidates per call`; `verify timeout → uncertain with code`; `protected colour ΔE 25 → rejected, reason contains both hex values`; `nudge validated only when direction and step match`; `shape uncertain in .6–.85 band`; `invalid licence rejected even when attributes pass`. Implement, pass, commit `feat(validation): per-kind validator with batched verify`.

### Task 14: Runs

**Files:** `app/runs/{orchestrator,summary}.py`, `app/api/runs.py`; Test: `tests/integration/runs/test_orchestrator.py`, `tests/integration/api/test_runs.py`

**Interfaces — Consumes:** T8 profile, T10–T13. **Produces:**
- `create_run(session, board_id, req, idempotency_key) -> Run`: validates (T10); snapshots source attributes, `lens_id`, `board_profiles.version`, `RANKING_CONFIG`, `VALIDATOR_VERSION`, provider ids; status `queued`. Same key + same body → same run; same key + different body → 409 `IDEMPOTENCY_KEY_REUSED`. A 422 creates no run.
- `execute_run(session_factory, run_id)` (background task): `retrieving` (pool + exclusions; every pool item gets a `run_candidates` row, `excluded` with reason or `retrieved`) → `validating` (shortlist; candidates `validating` → final state; results written per batch; `run.progress {stage, validated_n, shortlist_n}` emitted over SSE) → select ≤6 validated with `select_diverse` → `completed`. Any exception → `failed` + `error_code`; rows already written stay.
- `summarize_run(...) -> {pool_size, excluded: {reason: n}, validated, uncertain, rejected, returned, shortfall?: [{code, count, message}]}`; `shortfall` present when returned < 6, with deterministic messages ("7 changed a protected attribute (primary colour)", "3 had uncertain density — under Needs review").
- `POST /api/boards/{id}/runs` (header `Idempotency-Key`) → 202 `{run_id}`; `GET /api/runs/{id}` → `{run, progress, summary, results (validated, ranked), needs_review (uncertain, ≤6), rejected, excluded_counts}`; each candidate view carries corpus provenance (credit text), scores, checks, observed target value, latest decision and decision history. A run non-terminal for > 5 min is marked `failed` `RUN_INTERRUPTED` on read.

- [ ] Failing tests (fixture corpus, mock providers): `explore colour on a fixture board returns ≤6 validated with distinct colours, none equal to source`; `fewer-than-six returns shortfall reasons`; `never returns source or duplicate`; `uncertain only in needs_review`; `run stores ranking version rank-2026.10-c, validator val-3 and profile version`; `same Idempotency-Key → same run, no duplicate rows`; `422 creates no run`; `provider timeout during verify → uncertain, run still completes`; `run on a fashion board never returns watch items`; `run.progress events emitted in stage order`. Implement, pass, commit `feat(runs): orchestration, summary, API`.

### Task 15: Decisions and kept items

**Files:** `app/feedback/service.py`, `app/api/decisions.py`; Test: `tests/integration/api/test_decisions.py`

**Interfaces — Produces:**
- `REJECT_REASONS = ["wrong_target_change", "protected_changed", "image_quality", "not_on_brief", "duplicate_feel", "not_my_style", "other"]`.
- `record_decision(session, run_id, candidate_id, decision: 'keep'|'reject', reason_code?, note? (≤500 chars), mark_not_this: bool = False, idempotency_key?)`:
  - candidate must belong to the run (404 otherwise) and be `validated` or `uncertain` (409 `CANDIDATE_NOT_DECIDABLE` otherwise);
  - `reason_code`/`note` only with reject (400 otherwise);
  - appends a `decisions` row (board id, run id, candidate id, corpus item id, decision, reason, note, timestamp) — never updates;
  - **keep** creates (once, idempotent per candidate) a board item: `origin='candidate'`, `rights_status='licensed'`, `corpus_item_id`, `parent_item_id` = run source item, position to the right of the parent (parent.x + parent.w + 24, parent.y), copies corpus attributes as the item's attributes, emits `item.added` and requests a profile recompute; stores `decisions.item_id`;
  - **reject** with `mark_not_this=True` also creates the board item with `role='counter_example'` (so its values feed counter-signals); without it, nothing else changes;
  - project preferences are never written.
- `POST /api/runs/{id}/candidates/{cid}/decisions` → 201 `{decision, history, item?}`; `GET /api/boards/{id}/decisions.csv`.

- [ ] Failing tests: `keep persists with board, run, candidate and timestamp`; `keep creates exactly one linked item even when posted twice`; `kept item carries licence credit and parent link`; `keep→reject appends; history has both; latest is reject`; `reason on keep → 400`; `decision on excluded candidate → 409`; `candidate from another run → 404`; `reject without mark_not_this leaves board items and profile unchanged`; `reject with mark_not_this creates a counter_example item`. Implement, pass, commit `feat(feedback): decisions, keep onto board, not-this`.

### Task 16: Chrome extension

**Files:** `extension/manifest.json`, `src/{background,content,popup,capture,pair}.ts`; Test: `extension/tests/capture.test.ts` (Vitest + jsdom), Playwright with `--load-extension` in T19.

**Interfaces — Produces:**
- Manifest V3; permissions `contextMenus`, `activeTab`, `scripting`, `storage`; `host_permissions` only for the backend origin. No broad host permissions: capture uses `activeTab`.
- **Pairing:** the app shows a 6-digit code and the popup takes it. `POST /api/extension/pair` returns a token stored in `chrome.storage.local`. The backend stores only its hash.
- **Context menu "Add to board":**
  - on an image: fetch the `srcUrl` from the page context (it is visible to the user)
  - if that fails or is CORS-blocked: `captureVisibleTab` + crop to the element rect × devicePixelRatio
- **Context menu "Add this video to board":**
  1. pause the video
  2. capture the current frame via `captureVisibleTab` + crop
  3. optionally step +1 s ×3 for up to 4 frames
  4. send `frames_b64[]`
- **Popup "Add this page":** reads `og:image`, `og:title` and the canonical URL from the DOM (no network call), plus the creator handle where the page shows one: an Instagram `header a[href^="/"]`, a Pinterest pin "saved by"/source attribution. Selectors live in a small per-site table with a generic OpenGraph fallback; a missing handle stays null.
- Board picker (recent boards) and a toast on success with "Open board".
- Every capture sends `source_url`, `page_url`, `page_title`, `creator_handle?`, `kind`, `captured_at`.

- [ ] Failing tests:
  - `crop rect scales by devicePixelRatio`
  - `og parsing falls back to first large img`
  - `handle selector returns null when absent (never guessed)`
  - `unpaired extension shows pairing screen`
  - Commit `feat(extension): one-click capture to board`.

### Task 17: UI — canvas, add flow, context

**Files:** `frontend/src/canvas/*`, `panels/{ContextBar,AddMenu,Onboarding,BoardSignals,LensReview}.tsx`; Test: component tests

**Interfaces — Produces:**
- **Canvas:** infinite pan (space+drag / two-finger) and zoom (ctrl+wheel / pinch, 10%–400%), with a dot grid at low opacity. Items are Konva `Image` nodes with **no stroke, no corner radius, no shadow, no padding**.
- **Hover:** a 1 px outline drawn 4 px **outside** the image, plus a parse-status dot (8 px) at the top-left outside corner. Processing shows a slow shimmer over the image at 8% opacity.
- **Selection:** 4 corner handles outside the image, multi-select by shift-click or marquee, a floating `ItemToolbar` above the selection.
- **Video items:** the chosen frame is shown, with a small frames strip under the image on hover; click a frame to choose it.
- **Link items** (unparsed): a text card with the domain favicon, title and "Use the extension to capture this".
- **Lineage:** a thin curve from parent to kept candidate, shown only when either is selected.
- **Add:** drop files anywhere on the canvas (placed at the drop point), paste an image or URL (⌘V, at the viewport centre), or use the `AddMenu` (+ button): Upload images or video, Paste a link, Get the Chrome extension (pairing code).
- **`ContextBar`** (top-left, floating): board title (inline edit) and context, a one-line brief. Clicking it expands to a textarea plus an optional domain picker (Auto, Watch, Fashion, Interior, UI, Other…). Auto = inferred from the board.
- **`BoardSignals`** (right edge, collapsible): lens chip with origin; signals as rows ("Brushed steel · 7 of 9", with colour swatches); tensions ("Dial: black 4 · blue 3"); counter-signals. It updates live from SSE with a subtle highlight on change.
- **`LensReview`:** appears when a lens is proposed; lists parts (with SAM hit rate) and attributes by kind; Confirm, or Edit.
- **`Onboarding`** (empty board only): three steps on the canvas itself.
  1. "Name this board and say what it's for" (focuses the ContextBar)
  2. "Add references" (drop zone hint + AddMenu)
  3. "Add 5 to unlock board intelligence" (progress dots)
- **Keyboard shortcuts:** `V` vary, `I` inspect, `X` mark not this, `Del` remove, `F` fit to screen, `⌘Z` undo position changes.

- [ ] Failing tests:
  - `image node has strokeWidth 0 and cornerRadius 0`
  - `hover outline is offset outside bounds`
  - `drop places item at pointer in canvas coords under zoom`
  - `paste URL calls ingest link`
  - `onboarding hidden once 1 item exists`
  - `signals panel updates on profile.updated event`
  - Commit.

### Task 18: UI — inspect, vary, Maybe strip, decisions

**Files:** `panels/{ItemToolbar,InspectPanel,VaryPanel,MaybeStrip,CandidatePopover}.tsx`

**Interfaces — Produces:**
- **`ItemToolbar`** (one selected item): Vary · Inspect · Not this · Open source · Remove. For several selected: Compare · Not this · Remove.
- **`InspectPanel`** (right drawer, replaces BoardSignals while open): attribute rows by category. Each row has a kind-specific editor:
  - enum: select
  - ordinal: segmented scale
  - number: stepper with unit
  - boolean: toggle
  - color: swatch + hex
  - text: input
  - shape: outline thumbnail

  Rows also have status chips, Confirm, the enable switch, History and "Vary this". A row that is a board signal is marked "board signal".
- **`VaryPanel`** (opened from toolbar, row or `V`), in four steps:
  1. Pick a target attribute; the list is sorted with tensions first.
  2. Pick a mode. Explore, Prefer and Avoid apply to every kind; Nudge more/less applies to ordinal and number only and shows the scale with the next step highlighted.
  3. Review protected chips, pre-filled and ordered by board signal.
  4. Read the preflight sentence and press Run.
- **`MaybeStrip`** (docked bottom, borderless thumbnails, 120 px tall):
  - shows run progress ("Checking 8 of 16")
  - validated candidates appear left to right as they land
  - a "Needs review" divider, then the uncertain ones
  - a "Why only 3?" link opens the shortfall summary
  - state is shown by a 3 px bar **under** each image (validated blue, uncertain amber), never a border
- **`CandidatePopover`** (click a strip item): large image, credit line, target change, checks (✓ ✕ ?, with swatches/scale/shape outline per kind), then Keep (flies onto the canvas beside the source) and Reject (reason chips + "Mark as not this").
- **Compare** (2–4 items selected): a table of attributes where the items differ, with a "Vary toward this" shortcut.

- [ ] Failing tests:
  - `nudge only offered for ordinal/number`
  - `preflight sentence lists target, mode and protected`
  - `strip state bar not border`
  - `keep adds item to canvas next to source`
  - `compare shows only differing attributes`
  - Commit.

### Task 19: End-to-end, README, deploy

`demo-flow.spec.ts` (mock providers, fixture corpus), in order:
1. Create a board and type the context.
2. Upload 3 images and drop 2 more; the onboarding progress fills.
3. The lens is auto-chosen (watch); signals appear live.
4. Paste a link to a fixture page with `og:image`; it becomes an item.
5. Upload an MP4; frames appear; choose frame 2.
6. Select an item, Vary dial colour (Explore), Run.
7. Candidates stream into the Maybe strip; open one; Keep it, and it lands on the canvas with a lineage curve.
8. Reject one with "not my style" and mark it as not-this; counter-signals update.
9. Nudge "legibility: more" on another item.
10. Reload; everything persists.

Plus `extension.spec.ts`: load the built extension, pair, right-click a fixture image, and confirm the item appears on the board. Then the full command suite, README, deploy.

---

## Calendar (IST)

| Day | Tasks |
|---|---|
| Tue Oct 27 | T0 smoke gate, T1, T2 |
| Wed Oct 28 | T3, T4, T5 |
| Thu Oct 29 | T6, T7, T8; start T9 import + overnight index |
| Fri Oct 30 | T10–T13; backup video |
| Sat Oct 31 | T14, T15, T17 canvas; designer session 1 |
| Sun Nov 1 | T16 extension, T18; designer sessions 2–5 |
| Mon Nov 2 | T19, deploy |
| Tue–Wed Nov 3–4 | eval, video, submit before 07:30 IST Nov 5 |

**Cut order if late:**
1. `shape` kind (already flagged)
2. SAM video tracking
3. Compare
4. Extension video capture (keep image + page capture)
5. Nudge for `number` (keep ordinal)

**Never cut:** canvas add flow, parsing, board signals, Vary + Maybe strip + keep onto canvas, credits.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_API_KEY` | — | Meta Model API key (`LLM_…`) |
| `META_BASE_URL` | `https://api.meta.ai/v1` | |
| `REASONING_PROVIDER` | `mock` | `mock` \| `muse-spark` \| `muse-spark-open` |
| `MUSE_SPARK_MODEL` | `muse-spark-1.3` | never `*-contributor` |
| `SEGMENTATION_PROVIDER` | `mock` | `mock` \| `sam-3.1` |
| `EMBEDDER` | `mock` | `mock` \| `siglip2` \| `pe-core` |
| `BASETEN_API_KEY` / `BASETEN_MODEL` | — / `meta-models/muse-spark-open` | optional |
| `PEXELS_API_KEY` / `PEXELS_ENABLED` | — / `0` | gated |
| `OPENVERSE_CLIENT_ID` / `OPENVERSE_CLIENT_SECRET` | — | registered access |
| `SMITHSONIAN_API_KEY` | — | api.data.gov key |
| `CONTACT_EMAIL` | — | Wikimedia User-Agent |
| `MODEL_TIMEOUT_S` / `MODEL_MAX_RETRIES` | `60` / `2` | |
| `DATABASE_URL` | `sqlite:///./data/dle.sqlite` | |
| `DATA_DIR` | `./data` | uploads, frames, masks, embeddings |
| `MAX_UPLOAD_BYTES` | `10485760` | |
| `MAX_VIDEO_BYTES` / `MAX_VIDEO_SECONDS` | `104857600` / `90` | |
| `LINK_FETCH_TIMEOUT_S` | `5` | |
| `SHAPE_KIND_ENABLED` | `0` | |
| `EXTENSION_ORIGIN` | — | CORS allow-list for `chrome-extension://<id>` |
| `PUBLIC_APP_URL` | `http://localhost:5173` | |
