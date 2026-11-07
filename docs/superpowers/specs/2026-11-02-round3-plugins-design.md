# Round 3: plugins that make options (Variation · Color, Clean-up, 3D, Animate)

Status: design, agreed in conversation 2026-11-02, revised 2026-11-04 against main `b7c2948`
(item analysis engine, living board, put-into, board agent and chat landed in between).
Builds on round 2's plugin engine (`backend/app/plugins/`, node UI in `frontend/src/plugins/`).

## Intent

A plugin is **a piece of code you attach to items on the board that makes options**. It has
inputs (items wired in), knobs (controls on the node card), and outputs (new options placed on
the board). It is not a report generator and not "a model call with a prompt": a model is one
tool a plugin may use, and the best plugins use none. The owner's words: "the plugin are not
just manipulators they are piece of code", and "the board has to work with everything and
anything".

Round 2 shipped the engine (manifests, python / llm / model runners, node cards) with three
plugins that run (Image, Palette, Critique) and thirteen placeholders. Round 3 connects the
ones that matter for design options now, and builds the shared pieces every later plugin
(including user-made ones) will reuse.

Reference mockups (from the owner, 2026-11-02): a "Variation" node wired to a shoe with a
Form / Color tab, a named palette ("Coral Bay", five swatches) with shuffle and copy icons, a
count and **Generate**, producing a 4-wide grid of colourways beside it; an "Animate" node with
Type, Duration, Prompt + **Describe**, Start / End frame slots with a swap, and **Animate**,
producing a video beside the source.

## Goals

1. **Variation · Color**: recolour an item part by part from a palette, deterministically,
   with no image generation. Many options per press, free to run.
2. **Clean-up**: cut the item out of its background and crop it, deterministically.
3. **3D model**: one item → a textured 3D model on the board, via fal.
4. **Animate**: image (+ optional end frame) + prompt → a short video on the board, via fal.
5. The shared groundwork these force, built generically so user plugins get it too:
   richer knobs, part and object masks for python plugins, a grid layout for option batches,
   video and 3D outputs, long-running jobs, inline video playback, a 3D viewer, and caps on
   paid plugin steps.

## Non-goals (later rounds)

- Variation **Form** tab. The tab is not shown at all this round.
- Upscale.
- Adding plugins through a coding agent over MCP (local first, hosted later — future scope).
- The document-style placeholders (tech pack, BOM, language card, compare, webfill), `fit`,
  `formula`, `texture`, `frames`, and the `code` sandbox. They stay "not connected".
- Hosted user plugins.
- The open-beta guard (tester identity, board ownership, DB-backed counters,
  `2026-10-29-open-beta-fly-design.md`). It is design only and not on main; round 3 uses the
  guard that exists today and does not build open-beta.
- Making Variation an explore "renderer" (`backend/app/render/registry.py`). It stays a plugin
  node.

## Anti-goals (would be a failure even if it works)

- Variation calling an image model. It is computer vision over masks; zero model calls once
  the item's part masks exist.
- A paid plugin step (3D, Animate, Describe) running without passing the board's daily cap,
  or retrying a paid submit automatically.
- Any secret (`FAL_KEY`, `MODEL_API_KEY`) reaching a python plugin's environment. Paid calls
  are made by the host, never by plugin code.
- A run that silently vanishes on page reload or server restart while fal is still working.

## Constraints carried over

- Python plugins run through the existing shim (`sys.executable -I`, stripped env, timeout,
  stdout cap, process-group kill). Built-in plugins only on the hosted site; user plugins from
  `PLUGINS_DIR` never load in `DEMO_MODE`.
- Access: `DEMO_MODE` + passcode (`backend/app/demo.py`, `demo_guard` in `main.py`). A plugin
  run is a write, so in demo mode only passcode-unlocked sessions can run one. Unchanged.
- Board events go out after commit (`after_commit`), jobs through `app.jobs`.
- A plugin whose `requires` setting is unset shows "not connected" (`registry.status`).
- The board agent's generic `run_plugin` tool (`backend/app/agent/tools/run_plugin.py`) must
  be able to run every new plugin with plain params: each manifest gets a clear
  `description` and a params schema the agent can fill (widgets are UI hints only).
- Living board: placement must respect the living layout (`frontend/src/living/`); new items
  must not overlap existing bodies (use the same free-slot / placement helpers writeback and
  extract use).

## What main already gives us (checked 2026-11-04)

- **Per-item parts.** The item analysis engine stores each item's own parts in `item_parts`
  (`ItemPart`: `key`, `label`, `region_kind` mask | box | text_range, `mask_path`, `source`,
  `removed`; up to 8 AI parts per item; people can add and rename parts and those survive
  re-analysis). Analysis runs automatically on ingest (one Spark call per item, metered as
  "analyse").
- **Lazy masks.** `analysis/locate.py: locate(session, item_id, part_key) -> Region` runs SAM
  the first time a mask part is needed, caches it in `part_masks`, and returns the mask file.
  Masks are PNGs, 255 = in the part.
- **Extract.** `analysis/extract.py: extract(session, item_id, part_key)` crops a part onto a
  transparent background as a new linked item.
- **In-region composite.** `render/composite.py: composite_in_region(...)`, a feathered blend
  through a mask.
- **Caps.** `analysis/limits.py: check_and_count(board_id, kind)` / `refund(...)`, per-board
  daily windows for "analyse" (300) and "render" (60). In-memory: a restart resets them.
- **Plugin engine** still wired on the living board. Output kinds are images, notes,
  attributes, text, table; writeback stacks outputs in one column; plugin outputs are ordinary
  (not staged) items. `ModelName` already lists `video.generate` and `mesh.from_image`, but
  `_run_model` only runs `image.edit` / `image.generate`.
- **Video items** exist (ingest, frames strip, "▶ video" badge) with no inline playback.
  Nothing for 3D / GLB anywhere.

## Decisions

### Variation · Color (python runner, built-in id `recolor`, display name "Variation")

The id is `recolor` because `variation` already names the old Vary pipeline
(`VariationRun`, `runs/orchestrator.py`).

What the owner decided:
- Colour only. Pick a palette and it is applied across the item's parts.
- **Auto** mode: with count N, produce N different assignments of the palette's colours to the
  parts, skipping poor ones (same colour on two touching parts). Laid out as a grid.
- **Shuffle**: a fresh random assignment from the same palette; Generate again gives a new grid.
- **Manual** mode: choose which part gets which colour.
- No generation: a cheap CV algorithm over SAM part masks.

My calls:
- **Parts** are the item's own analysed parts with `region_kind = mask` and not removed.
  Before the run the host calls `locate` for each so every mask exists (SAM once per part,
  cached; see "Part and object masks"). A person who wants another part ("toe cap") adds it
  with the existing part-label flow; it then appears in the plugin. If an item has fewer than
  two mask parts the node says "this item needs at least two parts" and offers to re-analyse.
- **Overlapping masks**: a pixel belongs to the smallest part that covers it (laces win over
  the upper). Resolved once into a label map before recolouring.
- **Recolour method**: convert to CIE Lab; inside each part keep per-pixel lightness detail
  (L minus the part's mean L), move the part's mean L partway toward the target colour's L
  (so dark↔light swaps read right but shading, stitching and mesh texture survive), and set
  a/b to the target's a/b. Feather part edges 1–2 px. Pixels outside every part are untouched.
- **Adjacency**: two parts touch when their regions, dilated a few pixels, overlap. Auto mode
  never gives touching parts the same colour when the palette has enough colours; with fewer
  colours than needed it allows repeats, least-touching pairs first.
- **Determinism**: assignments come from a seed. Shuffle rerolls the seed. Same item + palette
  + seed + count ⇒ same grid.
- **Count**: 1–24, default 8. Auto may return fewer if there are not N distinct acceptable
  assignments (the node says how many it found).
- **Palettes** come from: a starter set shipped with the plugin (`x-presets` on the palette
  param in `plugin.json`, ~12, "Coral Bay" among them); palettes the Palette plugin has already written onto board items; and hand
  edits to any swatch. A palette is a name + 2–8 hex colours.
- **Inputs**: one image item per run (the grid is per item).
- Lives at `backend/app/plugins/builtin/recolor/` (`plugin.json`, `main.py`, `recolor.py`). Lab helpers are copied in rather than imported, since the shim runs
  plugins isolated.

### Clean-up (python runner, built-in id `cleanup`, replaces the placeholder)

My calls (owner agreed it should be cheap CV, and that 3D starts from a clean cut-out):
- Cut out the whole item using its **object mask** (new, see below), crop to the mask's
  bounding box plus a small margin, output a new image. Knob: background = transparent | white
  (default transparent). No model calls once the object mask exists.
- `extract` stays the way to cut out **one part**; Clean-up is the whole object. Clean-up
  shares the crop / alpha code with `extract` (lift `_crop` into a shared helper rather than
  duplicating it).
- Its own node, and used host-side by 3D before upload.
- The manifest's runner changes from `llm` to `python`; `requires` drops the placeholder.

### 3D model (model runner on fal, built-in id `mesh`)

What the owner decided: fal.

My calls:
- Model: Hunyuan3D on fal (image → textured GLB). Knobs: **Quality** fast | detailed (fast =
  the turbo/mini variant, detailed = the full one) and **Texture** on/off. The builder
  verifies the current fal endpoint ids, request fields and prices before wiring; the
  research figure is ~$0.08 per fast generation (fal listing, 2026-10).
- Input: one image item, cleaned first with Clean-up's code (host side), so fal always gets
  a cut-out.
- Output: a new **3D model** item beside the source, with a poster image (a rendered view or,
  if rendering is not practical server-side, the cleaned input) and the `.glb` file.
- `requires: ["FAL_KEY"]` (replaces `MESH_MODEL`); `runs_on` "fal · Hunyuan3D".

### Animate (model runner on fal, built-in id `video`)

What the owner decided: in this round, on fal; knobs as in the mockup.

My calls:
- Knobs: **Type** standard | pro (two fal image-to-video models that accept a start and an end
  frame, e.g. a Kling standard/pro pair — builder verifies current endpoints and that the end
  frame is supported); **Duration** 5 | 10 s; **Prompt** text with a **Describe** button;
  **Start** and **End** frame slots; **⇆** swaps them.
- **Frames are params that reference board items**, not wired roles: wiring an item fills
  Start; End is optional and filled by dropping or picking an item. The host validates each
  reference at run time (same board, image kind, not deleted).
- **Describe** writes a short motion prompt from the start frame with Muse Spark (existing
  reasoning provider). It is a paid call: unlocked sessions only, counted against the cap.
- Output: a **video** item beside the source (the existing video item kind and ingest path).
- Rough cost $0.25–1 per clip depending on type and duration (aggregator prices; builder
  confirms).
- `requires: ["FAL_KEY"]`; `runs_on` "fal".

### Groundwork

**Richer knobs.** Today a node card renders params as enum / integer / boolean / json / text
fields (`frontend/src/plugins/NodeCard.tsx`). Add an `x-widget` hint on a param's JSON schema,
rendered by the node card, usable by any plugin:
- `segmented` — an enum shown as tabs.
- `palette` — a named list of hex colours: swatches, edit one swatch, pick from starter and
  board palettes, copy.
- `seed` — an integer shown as a shuffle button (rerolls).
- `part-colors` — a map part key → hex, listing the input item's parts by label (manual mode).
- `frame` — a board item reference slot (drop or pick an item); two `frame` params may be
  linked by `x-swap-with` to show ⇆.
- `prompt` — multi-line text; `x-describe: true` adds a Describe button that calls a
  host-side describe endpoint for that plugin.
Unknown widgets fall back to today's plain field. Existing `x-show-if` keeps working. The
agent sees the plain schema (types, enums, ranges) and ignores widget hints.

**Part and object masks for python plugins.** A manifest may declare `"needs": ["parts"]`
and/or `["object_mask"]`. Before the run, the host:
- for `parts`: calls `locate` for each mask part of each image input and writes the masks as
  read-only PNGs into the run folder, adding `"parts": [{"key", "label", "mask_path"}]` to that
  input's payload;
- for `object_mask`: gets the item's object mask and adds `"object_mask_path"`.
The **object mask** is new: one SAM call prompted with the item's subject (its analysed
label / title), cached in `part_masks` under a distinct prompt (e.g. `object:<label>`), made
lazily like part masks. These SAM calls are counted under "analyse" (today `locate` is not
metered; mask preparation for plugins is, with a refund on failure).

**Option batches and the grid.** The python runner may return up to 24 images per run (the
model runner keeps its 8). Writeback lays a run's outputs out as a grid beside the node
(4 wide, using the free-slot placement so nothing overlaps on the living board) instead of
one column. Outputs of a run with more than one image arrive as **options**: ordinary
generated items carrying the run id and an `option` flag, drawn with a light outline. You can
keep several (Keep clears the flag), wire an option into another plugin (e.g. a colourway
into 3D), and **Clear** on the node deletes that run's items still flagged (undoable). Single
outputs (3D, Animate, one Clean-up) are plain items. (Not round 2's `staged`, which hides
items from the canvas.)

**New output kinds.** `video` and `model3d` join `OUTPUT_KINDS`. Writeback stores the file
via `app.storage.files`, creates a `video` item (existing kind) or a new `model` item kind
(GLB + poster), and places it beside the node. Size caps: video as the existing ingest cap,
GLB 50 MB.

**Long jobs.** fal calls go through fal's queue API: submit, then poll status, then fetch the
result. The run row stores the fal request id and status; the node shows progress messages.
On server restart `recover_stuck_runs` resumes polling stored request ids instead of
resubmitting. A paid submit is never retried automatically; a failed or timed-out run says so
on the node and refunds its cap slot. Overall timeout 10 min (configurable).

**Board viewers.** Video items play inline on the board (click to play/pause, muted by
default). Model items show their poster on the canvas and open an interactive 3D viewer
(orbit, zoom) in an overlay with a Download `.glb` action. Viewer library is the builder's
choice (e.g. `<model-viewer>` or three.js), loaded lazily.

**Caps on paid steps.** Use the existing per-board daily limits (`analysis/limits.py`):
- add kinds `"mesh"` (default 10 per board per day) and `"video"` (default 10), with settings
  `MESH_PER_BOARD_PER_DAY` and `VIDEO_PER_BOARD_PER_DAY`;
- Describe counts as `"render"`; first-time mask preparation counts as `"analyse"`;
- free steps (recolour and clean-up once masks exist, Palette) are not counted;
- check before submit, refund on any failure before or during the paid call that left the
  person with nothing (as put-into does).
These windows are in-memory and reset on deploy, the same as today's caps. Making them
survive restarts belongs with the open-beta guard, not this round.

**Settings.** `FAL_KEY` (secret), optional fal endpoint id overrides per plugin, the two new
per-board limits.

**Agent.** No registration needed: `run_plugin(plugin_id, input_item_ids, params)` already
covers new plugins. Each new manifest's description and params must make sense to it (e.g.
`recolor` params: `mode`, `palette`, `seed`, `count`, `part_colors`). The board-agent design
prefers exploring the colour dimension for checked colourways; that stays its choice.

## Order of work (suggested)

1. Knob widgets + part / object masks for python plugins + grid / options writeback.
2. Variation · Color.
3. Clean-up.
4. Long jobs on fal + caps + new output kinds + viewers.
5. 3D.
6. Animate (with Describe).

## Left to the builder

- Exact fal endpoint ids, request/response fields, and current prices (verify, don't trust the
  figures above).
- The 3D poster rendering approach.
- Viewer library.
- Starter palette names and colours (Coral Bay included).
- Internal module layout for the new widgets and the fal client.
- Where the `option` flag lives (a column on `board_items` vs plugin run provenance).

## Done means

- On a local board: wire Variation to an analysed shoe with several mask parts, pick a
  palette, Generate 24 → a grid of distinct part-wise colourways appears in seconds with zero
  model calls (masks already made); Shuffle → a different grid; Manual mode sets chosen parts'
  colours; Keep and Clear behave as above.
- Clean-up produces a cropped cut-out of the whole item.
- With `FAL_KEY` set: 3D produces a model item that opens in the viewer and downloads as a
  GLB; Animate produces a playable video item; both survive a page reload and a server restart
  mid-run without a second paid submit.
- With `FAL_KEY` unset, 3D and Animate show "not connected".
- In demo mode: locked sessions cannot run anything; unlocked paid runs stop at the board's
  daily caps with a clear message.
- The board agent can run each new plugin through `run_plugin`.
- Backend, frontend and e2e suites green; lint clean.
