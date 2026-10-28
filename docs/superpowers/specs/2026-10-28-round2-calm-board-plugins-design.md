# Round 2: calm board, text-first axis, notes, plugin nodes (design)

Date: 2026-10-28. Status: draft for approval. Branch `feat/round2-calm-board-plugins`, worktree `../muse-round2`, based on `feat/explore-visualize` at `d881f44`.

Source of the UI: the "Muse Spark — app interface" design canvas, Round 2 row (artboards `BoardCalm`, `NoteNode`, `ActionNodes`, `Plugins`), and the design chat that produced it. The artboards are the visual reference; this document is the behaviour.

## Intent

The board feels crowded: every feature in every state at the same weight, caps labels, explainer lines. Round 2 makes the board mostly images and words, and turns the heavy actions into **nodes** that come from **plugins**.

The user's model, in their words from the design chat:

- When you drag out an axis you see the variants **in text**; click one and **Visualize** it; then **Regenerate** or **Keep**. A kept variant replaces its text card with the image.
- **Notes** are content on the board. A note has a Visualize button on hover; the image lands next to the note.
- **Nodes are actions.** Image generation, video generation, 2D image → 3D, a Python code block: each takes input from the board and puts output back on the board. They are **plugins** you install per project workflow, and **users can make their own**: a simple deterministic Python function, an LLM node with structured output, anything.
- Video is a placeholder for now. The plugin backend is built now so later nodes slot in.

## Goals

1. **Calm board shell** replaces today's board screen (not behind a switch).
2. **Text-first axis**: explore options laid out along a line from the source image; click → Visualize → take image in a card → Regenerate (take 2, 3…) or Keep; kept options show their image on the axis.
3. **Notes** as a new board item kind, created with `N` or the Note tool, with hover **Visualize** (text → image, using the note plus board context).
4. **Plugin engine** (backend): manifests, discovery from built-in and user folders, three runner kinds (`python`, `llm`, `model`), per-board install, runs as background jobs with live events, outputs written back to the board with lineage.
5. **Node cards** on the canvas for added plugins: inputs, settings, output preview, Run.
6. **Plugins panel**: workflow packs (Product design, Fashion, Interior, Automotive, Formulation lab, All) with Add / Added per plugin.
7. Built-in plugins that **work**: Image (part edit or whole image), Palette (deterministic Python), Critique (LLM, structured output). Built-ins that are **placeholders** ("model not connected"): Video, Image → 3D, Python code block, and the rest of the list in the Action nodes artboard.

## Non-goals

- The Muse agent loop (legal-agent-workshop structure). The agent card is a shell this round. But every plugin manifest must be convertible into a tool definition later (name, description, JSON-schema inputs), so plugins become agent tools without a rewrite.
- Wiring nodes to each other (a graph editor). Lines show where a result came from, not a pipeline you build.
- Vocabulary redesign (needs its own research). The rail icon opens a "coming soon" panel.
- Video axis, video generation, 3D generation, editable code-block node.
- A plugin marketplace, plugin upload through the browser, plugin versions/updates.

## Anti-goals

- Generating anything the user did not click for. Visualize, Regenerate and Run are the only triggers.
- **Running user plugin code on the public demo deploy.** User (non-built-in) plugins are never loaded when `DEMO_MODE=1`.
- Losing something that works today. Inspect, Explore's drawer list, Compare, Find real examples, board signals, lens review, upload/add, live search, undo must all stay reachable.
- Bringing back the slop: no all-caps section labels, no explainer line under every heading, one accent colour (`#2a4aae`) used for the active axis and selection only.

## The experience

### Shell (artboard `BoardCalm`)

- **Header** (one row, no border): back to all boards, board title, the board's context sentence in muted text. The current ContextBar editing stays (click title/context to edit), restyled. Demo badge stays.
- **Left rail**, 56 px wide, icon buttons with `aria-label`: Library, Search, Plugins, Vocabulary. Clicking one opens a slide-out panel beside the rail over the canvas; clicking again or `Esc` closes it. Library = the board's items list plus today's Add flow (upload, paste, link) and board signals + lens review. Search = today's live/corpus search from the Add menu. Plugins = the plugins panel (below). Vocabulary = "coming soon".
- **Canvas** fills the rest, rounded inner frame, dot grid (as the artboard).
- **Agent card**, floating bottom-right, 340 px: "Muse", the latest board event as one sentence (reuse the board UI event log on `main`), an input that is visible but disabled with placeholder "Agent coming soon", and an expand button that opens the event log. Hidden while a right-drawer panel is open.
- **Bottom toolbar**, floating centre-bottom: Select (`V` stays Explore as today; Select is `Esc`/default), Note (`N`), Axis (`A`), Nodes (opens a menu of the board's added plugins).
- **Right drawer** stays for item-scoped panels (Inspect, Explore list, Compare, Find real examples / Vary) and opens only from the item toolbar or a shortcut. MaybeStrip stays for retrieval candidates.
- **Chips on the canvas** only for the selected image item: up to 6 attribute chips under it (as `BoardCalm`), each with the source mark from the `Chips` artboard (measured / read / estimated / you / unknown). Clicking a chip starts an axis on that attribute.

### Text-first axis

1. Select an image, then the Axis tool (or click a chip, or pick an attribute in the Explore drawer).
2. The existing explore call returns options. They render as **text cards along a horizontal line** from the source's right edge, label "‹attribute label›" above the line, an end handle at the line's end. Cards: name (600), one-line description (muted). No distance/held badges on the card; distance shows as a single small dot (near/bold/wild shades) and the full status on hover/selection.
3. Click a card → a popover under it: "**Name**: description", then "Keeps ‹kept labels›. Only ‹attribute› changes." and **Visualize**.
4. Visualize → the popover shows progress, then the take image with "Name · take n", **Keep** and **Regenerate**. Regenerate makes another take (existing re-visualize). The popover can page between takes.
5. Keep → the card on the axis becomes the kept take's thumbnail labelled "Name · kept"; the popover closes. Clicking a kept card reopens it with **Un-keep** and **Regenerate**.
6. More / Further / steer and Branch from the explore branch stay, as controls at the axis's end handle (More, Further, steer box) and in the popover (Branch, Find real examples, Dismiss).
7. The drawer's Explore list and the axis stay in sync, as today with notes.

**Takes are staged, not loose on the canvas.** Today each visualize drops a generated item beside the option note. Now takes are board items marked **staged**: not drawn on the canvas, not counted in board profile/signals, listed in the option's popover. Keep un-stages the chosen take, records it as the option's kept item, and it is drawn in the card's slot on the axis (lineage line to the source). Un-keep re-stages it. The check verdict (target ✓, n of m kept) shows in the popover and on the kept card on hover.

### Notes (artboard `NoteNode`)

- `N` or the Note tool, then click on the canvas: a note appears in edit mode (sticky colour `#fff6d9`, 220 px wide, grows with text). Type, click away or `Esc` to save. Double-click edits. Delete/undo like other items.
- A note is a board item (`kind="note"`) with text, position and size; it is never parsed by image extraction.
- Hover/selected → a small bar under it: **Visualize** and "⋯" (Delete; "Send to node" lists added plugins whose inputs accept notes).
- Visualize → a placeholder card with progress appears beside the note with a dashed line; then the generated image replaces it, solid lineage line back to the note, caption "generated · ‹model›". This image is a normal canvas item (not staged). Visualizing again adds another image stacked below.
- Text → image prompt: the note text, plus the board title and context, plus up to 4 of the board's image references sent as images when the provider takes reference images (Muse Image generations does not today: then text only). Builder writes the prompt; start from "‹note›. Board: ‹title› — ‹context›. Product photo, plain background."
- Check after a note visualize: only the direct target question ("Does this image show: ‹note›?"), no kept attributes. Shown as a one-line verdict on the image.
- The explore option notes from the explore branch are **replaced** by axis cards; they are not user notes.

### Nodes and plugins (artboards `ActionNodes`, `Plugins`)

- Plugins panel (left rail): packs on the left, the selected pack's plugins on the right as rows: mark, name, what it does, "runs on ‹label›", Add/Added. A plugin whose runner is not available shows "Not connected" instead of Add-able state (it can still be added; its node says so). Footer: one line on what a plugin declares, and "Build a plugin" which opens `docs/plugins.md` rendered in a panel (or a link to it).
- Packs come from a static file; the "All" pack is every discovered plugin. Adding a plugin is per board.
- Nodes menu (bottom toolbar) lists the board's added plugins. Picking one places a **node card** on the canvas near the selection, with the current selection as its inputs. Items can also be dragged onto a node to add them as inputs. A node's inputs show as small chips (thumbnail + label, or "note"), removable.
- Node card (as `ActionNodes`): icon tile, name, "runs on" label, inputs chips, one settings line (the manifest's main params, e.g. "Change only: [part]" / "Whole image", "4 images"), output preview area, primary button **Run** (becomes **Run again** after a run), secondary button from the manifest (e.g. Prompt / Settings). Status while running: progress bar and the last progress message. Errors show inline in plain words.
- Run output lands on the board next to the node: new items (images, notes) with lineage lines back to the node's inputs; attributes written onto input items with source `plugin` and the plugin name as detail; a text/table/doc output is stored on the run and shown in the node's output area.
- Placeholder plugins render the full card with Run disabled and "‹Model› not connected" in the output area.

## How it works

### Backend

**Notes**
- `ITEM_KINDS` gains `"note"`; `ORIGINS` gains `"note"`. New nullable column `board_items.note_text`. Notes: `rights_status="user_supplied"`, no file, `parse_status="completed"` set at creation (extraction never runs on them; guard the parse paths by kind).
- `POST /api/boards/{board_id}/notes` `{text, x, y, w?, h?}` → item; `PATCH /api/items/{id}` accepts `note_text` for notes. Existing remove/undo paths cover delete.
- Notes are excluded from board profile, retrieval, compare and signals. The reasoning context builders that take "board context" include note texts (title, context, notes), capped (builder picks a cap, e.g. 20 notes / 2 000 chars).
- `POST /api/items/{note_id}/visualize` → background job like `visualize_option`: `ImageProvider.generate(prompt) -> bytes` (new method; `POST /v1/images/generations` was verified working on 2026-10-28; mock returns a deterministic tinted canvas), store as a generated item, `parent_item_id = note id`, placed right of the note (stack below earlier ones), then parse it and run the target check. Board events for progress, like option visualize. Same 409-while-running claim pattern.

**Staged takes and keep**
- New column `board_items.staged` (bool, default false). Option visualize creates takes with `staged=true` and stops placing them beside the note. Items listing returns staged items with the flag (the popover needs them); the canvas, profile, signals, retrieval and compare ignore staged items.
- New column `explore_options.kept_item_id` (nullable). `POST /api/options/{id}/keep` `{item_id}` → un-stages that take, re-stages a previously kept take of the same option, sets `kept_item_id`, places the item at the option's axis slot. `POST /api/options/{id}/unkeep` → re-stages it, clears `kept_item_id`. Option status gains `"kept"` (resting status after keep; un-keep returns to `visualized`).
- Alembic migration `0007_round2` (see "Settled after the builder check" for the chain) for the three columns and the extended check constraints. It must succeed on a populated database (the 0004 lesson: table rebuilds with FK checks deferred around the whole run).

**Plugin engine** (`backend/app/plugins/`)
- **Manifest** `plugin.json` in each plugin folder:
  ```json
  {
    "id": "palette",
    "name": "Palette & material",
    "description": "Swatches from a group of images.",
    "mark": "PAL", "tint": "#f3f4f6", "ink": "#3a4350",
    "runner": "python",
    "runs_on": "SAM 3.1 + Lab",
    "inputs": { "kinds": ["image"], "min": 1, "max": 12 },
    "params": { "type": "object", "properties": { "count": { "type": "integer", "minimum": 3, "maximum": 8, "default": 5 } } },
    "outputs": ["notes", "attributes"],
    "requires": [],
    "entry": "main.py"
  }
  ```
  - `runner`: `python` | `llm` | `model`.
  - `inputs.kinds` ⊆ `image`, `video`, `note`, `link`; `min`/`max` counts.
  - `params`: JSON Schema (object). The node card renders simple types (string, enum, integer, boolean); others fall back to a JSON text box.
  - `outputs` ⊆ `images`, `notes`, `attributes`, `text`, `table`.
  - `requires`: setting names that must be set for the plugin to be available (e.g. `["VIDEO_MODEL"]`); missing → status `not_connected`.
  - `python`: `entry` file with `def run(inputs, params, ctx) -> dict`. `llm`: `prompt` file (template with `{{params.x}}`, `{{notes}}`, `{{board.title}}`, `{{board.context}}`) and `output_schema` (JSON Schema) in the manifest. `model`: `model` = a built-in model binding name (`image.edit`, `image.generate`, `video.generate`, `mesh.from_image`); user plugins cannot use `model` this round.
  - The manifest must map to a tool definition: `{name: id, description, input_schema: {item_ids, params}}`. A unit test asserts every built-in converts.
- **Discovery**: built-ins at `backend/app/plugins/builtin/<id>/`, user plugins at `PLUGINS_DIR` (default `data/plugins`, gitignored). Loaded at startup and on `POST /api/plugins/reload`. Invalid manifests are skipped with a logged reason and listed by the reload endpoint's response. Ids are unique; a user plugin cannot shadow a built-in. `DEMO_MODE=1` → user plugins are not loaded.
- **Packs**: `backend/app/plugins/packs.json` (pack id, name, about, plugin ids). Unknown ids in a pack are ignored.
- **Storage** (migration `0007_round2` as well):
  - `board_plugins` (board_id, plugin_id, added_at; unique pair).
  - `plugin_nodes` (id, board_id, plugin_id, x, y, w, h, input_item_ids_json, params_json, last_run_id, removed_at, created_at).
  - `plugin_runs` (id, board_id, node_id, plugin_id, input_item_ids_json, params_json, status `queued|running|done|failed`, progress_json, output_json, error_code, error_message, claimed_at, created_at, finished_at).
- **API**: `GET /api/plugins` (all discovered, with status `available|not_connected`), `GET /api/plugin-packs`, `GET/POST/DELETE /api/boards/{id}/plugins[/{plugin_id}]`, `POST /api/boards/{id}/nodes`, `PATCH/DELETE /api/nodes/{id}` (position, inputs, params), `POST /api/nodes/{id}/run` → run id (409 while that node has a run queued/running, with the stale-claim TTL pattern), `GET /api/runs/plugin/{run_id}`.
- **Execution** (one job `plugin_run`, default queue):
  1. Load inputs: items (kind, metadata, attributes, note text, image bytes from the original file) and the board (title, context, notes).
  2. Validate input kinds/counts and params against the manifest → `PLUGIN_BAD_INPUT` (400 at request time when checkable, else a failed run).
  3. Dispatch by runner:
     - `python`: run `python -I <runner_shim.py> <plugin_dir>` in a **subprocess**, cwd = a fresh temp dir, environment stripped to `PATH`, `HOME`=temp dir, `PYTHONHASHSEED`. Input JSON on stdin: `{inputs: [{id, kind, label, attributes, note_text, image_path}], params, board: {title, context, notes}}`; image files copied into the temp dir read-only. Output JSON on stdout. Timeout 30 s (setting `PLUGIN_TIMEOUT_S`), stdout cap 1 MB, stderr kept (last 4 KB) for the error message. Built-ins use the same path (one code path to test). This is isolation from the app, **not** a security sandbox: it is for local, trusted plugins; say so in `docs/plugins.md`.
     - `llm`: render the prompt, call the reasoning provider's structured output with the input images (≤ the provider's image limit) and `output_schema`. Reuse the existing `extract(images, schema, prompt)`-style call (add a generic `structured` method if `extract` carries extraction assumptions). Mock provider returns schema-shaped deterministic output.
     - `model`: `image.edit` → `ImageProvider.edit` per input image with the prompt; `image.generate` → `ImageProvider.generate`; others → `not_connected`.
  4. Validate output: `{images?: [{data_b64 | path, caption}], notes?: [{text}], attributes?: [{item_id, key, value, label?}], text?: str, table?: {columns, rows}}`, only kinds the manifest declares. Unknown attribute keys are allowed (open attributes) with `source="plugin"`, `source_detail=<plugin id>`, `confidence=1` for python, provider confidence or 0.7 for llm.
  5. Write back: images → generated items (`origin="generated"`, `rights_status="generated"`, `generation_json` = `{plugin, model, run_id}`, `parent_item_id` = first input), notes → note items, placed in a column right of the node; attributes → upsert on the input items; text/table → `output_json`.
  6. Events: `plugin_run.queued|progress|done|failed` on the board stream, with node id and run id.
- **Built-in plugins this round**
  - `image` (model): params `mode` (`part` | `whole`), `part` (string, shown when mode=part), `prompt` (string), `count` (1–4). Part mode: edit prompt "Change only the ‹part›: ‹prompt›. Keep everything else exactly the same." Whole: edit with the prompt as is. Outputs `images`. Inputs: images and notes (note texts are appended to the prompt).
  - `palette` (python): deterministic swatches from input images (reuse the logic in `app/measure/palette.py` by vendoring the pure function into the plugin folder, since plugin code runs outside the app). Outputs `notes` (one note listing the swatches with hex) and `attributes` (`palette` on each input).
  - `critique` (llm): inputs any; uses board title/context/notes; `output_schema` = `{points: [{verdict: "fits"|"misses"|"unclear", text}], summary}`; outputs `notes` (one per point) and `text` (summary).
  - Placeholders (manifest only, `requires` a setting that is not set): `video` (`VIDEO_MODEL`), `mesh` "Image → 3D" (`MESH_MODEL`), `code` "Python" code block (`CODE_SANDBOX`), and the ten "More nodes worth having" from the artboard (web fill, palette & material is the real one above, critique is real, video → frames, design language card, tech pack, cost & BOM, compare, texture, clean-up).
- Example user plugin shipped as documentation: `docs/plugins/examples/word-count/` (python) and `docs/plugins/examples/tagline/` (llm), with `docs/plugins.md` explaining the manifest, the I/O contract, the folder, reload, and the trust warning.

### Frontend

- New layout component for the board page (`BoardShell` or similar) replacing the current composition in `pages/BoardPage.tsx`; existing panels are re-homed, not rewritten, where possible.
- Canvas (react-konva): new node types — note (editable text; editing via an HTML overlay textarea positioned over the Konva node), axis (line, label, end handle, option cards, kept thumbnails), plugin node card (HTML overlay positioned to the canvas transform is acceptable if Konva makes the controls awkward; the card must be keyboard reachable). Lineage lines reuse `lineagePoints`.
- Tools state: `select | note | axis`, shortcuts `N`, `A`, `Esc`; existing shortcut guard rules (no shortcuts while typing).
- Data: react-query hooks for plugins, packs, board plugins, nodes, plugin runs; SSE handlers for `plugin_run.*` and note visualize events; staged items filtered out of canvas rendering.
- Undo covers note create/edit/move/delete, node create/move/delete, input add/remove. Runs and generations are not undone (their outputs can be removed).

### Feature flags

- `PLUGINS_ENABLED` (default on). Off → no rail Plugins icon, no Nodes tool, plugin endpoints 404.
- `EXPLORE_ENABLED` keeps its meaning; when off, the Axis tool is hidden.

## Constraints

- All existing tests keep passing (backend ~660, frontend ~165 at the base commit; record exact counts at the start), plus the e2e suite with mock providers.
- Image model only through the provider setting (Muse Image is dev-only from India; the user swaps the model for the demo).
- Demo mode: Visualize, Run and note Visualize require the passcode unlock when `DEMO_MODE=1`, like option visualize today. User plugins never load in demo mode.
- No new frontend runtime dependencies unless a task justifies one in review.
- Accessibility as in the design rules: real buttons, `aria-label` on icon buttons, 44 px touch targets for primary controls, 4.5:1 text contrast.

## Quality bar

Tests first for backend logic (manifest validation, discovery, runner dispatch, subprocess runner with timeout and bad output, write-back, staged/keep, notes, note visualize), frontend unit tests for shell, tools, axis layout, note editing, node card, plugins panel; e2e with mock providers for: note → visualize; axis → visualize → regenerate → keep → un-keep; add plugin → node → run palette → notes land. Subagent per task with review per task, final whole-branch review.

## Settled after the builder check

- **Merge `main` first.** `main` has `b5e1d6d` (board UI event log, subject filter, more live sources) and `59306b3`, which this branch's base lacks. Task 0 merges `main` into this branch. Migrations: `main` has `0004_corpus_subject_status` → `0005_ui_events`, the base has `0004_explore`, all after `0003`. Add an Alembic merge revision (`0006_merge_main_explore`, `down_revision = ("0005_ui_events", "0004_explore")`), then this round's migration `0007_round2` on top. The populated-database test runs the full chain on a copy seeded at `0003`.
- **Agent card source.** The browser merges two streams: the UI event log (`main`, browser-side actions) and the board SSE stream (server events: visualize, keep, `plugin_run.*`). The card shows the newest of either as one sentence; the expanded view lists both, newest first. Server events are not written into `ui_events`.
- **Axes persist and stack.** An axis is the drawn form of an exploration; it exists while its exploration has non-dismissed options. Every axis of a visible image is drawn, stacked downward from the image's right side, one row per attribute, in exploration creation order; the selected one uses the accent colour, others grey. Axis geometry is computed from the source item's position (no new position columns), so axes and their kept items move with the source. Kept items are positioned in their card slot when kept and follow the source when it moves (the browser moves them with the source in the same undoable move; the server stores the new positions). After reload every axis comes back.
- **Plugin attributes.** Plugins never overwrite an attribute whose `source` is `user` or whose status is confirmed/edited; such a write is skipped and reported in the run's output. Otherwise upsert with `source="plugin"`, `source_detail=<plugin id>`, `category="plugin"`, `kind` inferred from the value (str→text, int/float→number, bool→boolean), status the same value extraction uses for fresh model values. Values stay scalar: list-like results are stored as text (palette = `"#e6d7b4, #d9a85c, …"`). Re-extraction treats `source="plugin"` like user values (does not overwrite). Migration `0007` adds `plugin` to the `attribute_events.actor` constraint and logs plugin writes with actor `plugin`.
- **Existing explore data.** No data step: takes already on boards stay visible (`staged=false`), `kept_item_id` stays null. Old option note positions (`explore_options.x/y`) are no longer used for layout (axis cards are computed); the columns stay.
- **Plugin Python.** Python plugins run under the app's own interpreter (`sys.executable -I`), so the packages installed with the backend (numpy, Pillow, scikit-image, scikit-learn) are importable; a plugin cannot add dependencies this round. `docs/plugins.md` says so. Palette vendors the pure functions it needs from `app/measure/palette.py` but may import those libraries.

## Left to the builder

- Exact geometry of axis cards and node cards (follow the artboards), how many axis cards before "show all".
- Whether node cards are Konva or HTML overlay (keyboard reachability decides).
- Prompt wording for note visualize, the image plugin, critique.
- The context cap for notes in reasoning prompts.

## Claude's calls (for the user to check)

- The calm board **replaces** today's board screen (user's "yes" read as replace).
- Takes from axis Visualize are **staged** (hidden from the canvas until kept); note Visualize images land on the canvas directly.
- Python plugins run in a **subprocess with a timeout**, local trust only; user plugins are disabled in demo mode.
- The **Python code-block** node (type code in the browser) is a placeholder this round; Python plugins are real via folders.
- Built-in working plugins: **Image, Palette, Critique**. Everything else is a placeholder card.
- The agent card shows the latest board event and a disabled input; Vocabulary is "coming soon".
- The explore branch's option notes are replaced by axis cards.
- Rebase onto `feat/explore-visualize` if it moves; this branch merges after it.
