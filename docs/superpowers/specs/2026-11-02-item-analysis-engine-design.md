# Item analysis engine and the exploration map — design

Date: 2026-11-02 · Branch: `feat/item-analysis-engine` (from `main` 88ff2c4)
Source designs: the "Muse UI redesign — audit fixes" canvas
(https://claude.ai/artifact/NwDwTu4fdWejZJsJzz9PRa), artboards **Board canvas** (`Main.dc.html`),
**Axis card states** (`AxisCard.dc.html`) and **Exploration map** (`Flower.dc.html`), plus the
per-image dimension model (`DimensionModel.dc.html`) and other domains (`Domains.dc.html`).

## 1. Intent

Muse should be able to take anything put on a board, understand it, and let the person explore it.
The idea is one simple loop, run by the person, by the side agent, or both:

```
analyse → label → explore → render → keep ─┐
   ▲                                       │
   └────────────── new item ───────────────┘
        (extract also feeds back into analyse)
```

Today the loop is bent by a **board-wide lens**: one fixed list of parts and dimensions (watch, fashion,
interior, ui) is imposed on every item. A wave on a ring board gets asked about "Silhouette"; nothing
outside the lens can be explored. Options are drawn as rows of small text cards to the right of the image,
kept takes are hidden inside their card, and edits change the whole image.

This project makes analysis **per item and type-agnostic**, makes the loop's steps first-class functions
shared by the UI and the agent, and replaces the axis rows with the **exploration map** (part callouts,
dimension hubs, option petals).

The user's framing (keep this spirit): *the idea is simple; where analysis misses something, human
intelligence chimes in — directly or through the agent on the side.* The engine proposes; the person
corrects; corrections stick.

## 2. Goals

1. **Per-item analysis** for three item types end to end: **image**, **text** (notes and pasted text),
   **UI screenshot**. Each item gets its own parts and dimensions.
2. **Two kinds of dimension**:
   - **Physical** — sits on a part that can be segmented and indicated (dial, seat, nav bar, headline).
   - **Abstract** — a property defined by a prompt, not located on the item (what the picture is about;
     medium: photo / 3D render / illustration / art; mood; tone). Because each abstract dimension is a
     named prompt, the same definition can be reused, which is what makes a common vocabulary easy.
3. **The six loop functions** (§5) as API endpoints, shaped so a later agent can use them as tools.
4. **Exploration map UI** replacing chips, the Explore drawer, and axis rows (§6).
5. **Options are notes first.** Exploring never generates media. A person (or the agent) renders one
   option through the plugin that fits the item.
6. **Extract**: any physical part can be pulled out into its own linked item and explored on its own
   (interior → seat; door panel → control-panel close-up).
7. **Kept results are ordinary board items**, visible full size, with their own parts and flowers.
8. **Board context that grows**: the person's words plus a "What Muse has learned" section that updates
   as items are added.
9. **Existing boards keep working** without re-analysis (§7).

## 3. Non-goals (this project)

Deferred until this ships, in this order of likely follow-up: borrowing from references (drag a value onto
a part, orange hubs, multi-parent lineage), the Combine / Cross grid, the new Home screen, the Board panel
replacing Library, the new-board flow. Also out: analysis of video, code, graphs and flowcharts (the
engine's interface must admit them later, §4.1), minimap, force-directed relayout of the board.

## 4. Engine

### 4.1 One interface, one analyser per item type

```
Analyser (per item type)
  analyse(item, board_context) -> Analysis
    parts:       [Part]       # may be empty
    dimensions:  [Dimension]
    summary:     str          # one line, feeds board context
  locate(item, part) -> Region   # lazily, see 4.3
```

- `Part`: `id`, `label`, `region_kind` ∈ `mask | box | text_range`, `region` (filled by `locate`),
  `source` ∈ `ai | you`.
- `Dimension`: `key`, `label`, `type` ∈ `physical | abstract`, `part_id` (physical only), `prompt`
  (abstract only: how to read this property), `value`, `confidence`, `source` ∈ `ai | you`.
- New item types later (video, code, graph, flowchart) add an analyser; nothing above changes.
- The engine stays **domain-free**: no watch/fashion/interior vocabulary in code. The only fixed
  vocabulary is the two dimension types and the three region kinds.

| Type | Parts | Region | Abstract examples | Render plugin (default) |
|---|---|---|---|---|
| image | objects/regions named by the vision model | `mask` via SAM 3.1 on the part's label | subject, medium, mood | Muse Image, edit inside the part's mask |
| UI screenshot | interface elements (nav, header, card list, CTA) | `box` returned by the vision model (Muse Spark) — SAM is not used for UI | density, tone, hierarchy | Muse Image, edit inside the box |
| text | sections (headline, intro, list, quote) | `text_range` (char offsets) returned by Spark | tone, audience, length, argument | Muse Spark, rewrite that passage only |

UI screenshots are a separate item type from images. Detection: the analyser's first pass classifies an
uploaded image as `photo/art` vs `ui_screenshot`; the person can switch it (label step).

### 4.2 analyse cost and the board context

- **One Spark call per item** proposes parts *and* dimensions with values, given the board context. It
  replaces today's lens-driven extraction call (no extra cost per item).
- The board context passed in = the person's own words + "What Muse has learned" (§4.5) + the board's
  **abstract dimension definitions** in use, so abstract dimensions are reused by name across items rather
  than re-invented ("Medium" stays "Medium").
- All calls count against the existing daily budget cap (open-beta design).

### 4.3 Segmentation is lazy

SAM runs only when a part is first **hovered, opened or extracted**, not for every part up front. The mask
is cached (existing `PartMask` table, keyed by image sha + prompt). Until it exists, hover shows a
loading outline. Text ranges and UI boxes come back with the analyse call, so they need no second step.

### 4.4 Board-level dimensions are found, not imposed

A dimension (same label + type, physical ones also matching part label) seen on **2+ items** is offered to
the board — "Strap stitching · seen on 4 of 12 · Add to board?" — never added silently. A board dimension
is then asked for on later analyses (as a hint, not a requirement). Existing propose → confirm flow is
reused.

### 4.5 Board context that grows

- **Your words**: edited only by the person.
- **What Muse has learned**: regenerated as items are added/kept/rejected: recurring values (signals),
  what was kept vs rejected, open tensions ("round vs cushion, 7 vs 5"). Stored per board, shown in the
  existing board/brief UI (the full Board panel redesign is deferred). Fed into analyse and explore.

### 4.6 Masked edits

Muse Image's `edit(image, prompt)` takes no mask today. Render for a physical dimension does:
**generate the edit on the whole image, then composite back only the pixels inside the part's region**
(mask or box, slightly feathered). Nothing outside the part can change. If the provider later accepts a
mask natively, use it and keep the composite as a guarantee. Abstract dimensions edit the whole image,
labelled "whole image, no mask".

## 5. The loop functions

Each is an HTTP endpoint backed by one service function with a typed request/result, so a side agent can
later call the same functions as tools ("the hands are missing a part called lume, add it"). **The agent
itself is not in this phase** (user decision): no chat runtime, model loop or agent-card changes. Only
the shape is kept tool-ready: each function's request/result schema is defined once and exported.

| Function | Does | Builds on |
|---|---|---|
| `analyse(item)` | Runs the item's analyser; stores parts + dimensions; refreshes learned context; emits board events. Re-running keeps every `source=you` part/dimension/value. | extraction service, `ItemAttribute`, `PartMask` |
| `label(item, change)` | Add / rename / remove a part or dimension, correct a value, switch item type, change a dimension's type or prompt. Marked `you`; survives re-analysis. | attribute edit + `AttributeEvent` |
| `extract(item, part)` | Cuts the part out (mask or box crop on transparent/neutral ground; for text, the range becomes a note) into a **new item** placed beside the source, linked by `parent_item_id` + `extracted_part`, then runs `analyse`. Optional "clean up" is a separate render via a plugin. | new |
| `explore(item, dimension, direction?)` | Proposes options as **notes** (name, one-line description, near/bold/wild, the value, what it keeps). No media. "More" / steer / branch reuse today's batches. | `POST /items/{id}/explore`, `Exploration`, `ExploreOption` |
| `render(option, plugin?)` | Runs the plugin that accepts the item type for this dimension (default per §4.1), with the masked composite for physical dimensions; runs the **check** (target value reads as intended, other dimensions held, % change outside region); produces a staged result. | visualize + plugin runners |
| `keep(result)` | Un-stages the result as a **normal board item**, linked to its parent and option, placed in free space next to its petal; then `analyse(result)`. Un-keep reverses. | `/options/{id}/keep` — drop the hidden-behind-card behaviour |

`Dismiss` (Not this) stays on options and results.

## 6. Exploration map UI

### 6.1 Selecting an item

- Toolbar: **Inspect · Not this · Remove** (+ Open source when present). Chips under the image, the
  Explore drawer and its "What to explore" list are removed.
- **Part callouts** around the item, as in the Board canvas artboard: one small card per part, leader line
  to an anchor dot on the part, listing that part's physical dimensions with current values
  (`Hand style · syringe`). Callouts go on the side nearest their part.
- A dashed **"Whole item"** callout holds abstract dimensions (no mask).
- **Hovering a callout highlights the part's segmented region on the item** (mask overlay for images, box
  for UI, highlighted range for text). Hovering a dimension chip does the same.
- Each callout has **Extract** for its part. The callouts also accept "+ Add part" / "+ Add dimension"
  (label step).

### 6.2 Flowers

- Clicking a dimension opens a **hub** joined to its callout by a dashed line; options sit around the hub
  as **petals**, opening away from the item.
- Petal states: **note** (text card: name, near/bold/wild tag, one line) → **rendering** (spinner) →
  **rendered** (shows the result image/text, check line) → **kept** (green border). Drifted results show
  "✕ Case shape drifted: round → cushion. Not added." with **Retry, tighter mask** and are never added.
- Clicking a petal opens its card (per the Axis card artboard): description, "Changes **Hands** · keeps 12
  ✓", and **one render button named by what will run** — "Generate image · Muse Image, inside the Hands
  mask", "Rewrite passage · Muse Spark", or "Connect a renderer" (opens the plugin picker) when nothing
  accepts the item. Then Keep / Not this / More like this / Branch.
- A kept result is a full item: it gets its own callouts and can open its own flowers (branching again).
- **Any number of flowers can be open**, on any number of items.

### 6.3 Layout rules (the canvas must stay calm)

- **Board items never move** because of a flower. Positions the person set are fixed.
- Flowers are placed only into **free space**: hub and petals avoid every item, every callout and every
  other open flower. Placement is deterministic (same board → same layout) and stable: opening flower B
  never moves flower A.
- If there is no room at the default distance, the flower goes further out along its direction; the
  canvas grows; nothing overlaps.
- A flower can be **collapsed** to a small badge on its callout ("Hand style · 6 options · 1 kept") and
  re-expanded; collapsed state persists per person.
- Kept results are placed by the same free-space rule, next to their petal.
- Smooth: pan/zoom stays 60 fps with many flowers open; flowers outside the viewport are not rendered.

### 6.4 Text and UI items

Same interaction. Text: callouts sit beside the note, regions are highlighted ranges, rendered petals show
the rewritten passage inside the full text with the change marked. UI: like images, with boxes.

## 7. Existing boards

- **No board re-analysis** (user decision, supersedes the earlier "re-analyse them"). No bulk job, no
  banner. Existing items keep their current attributes, read into the new model as dimensions: an
  attribute with a part becomes physical on that part; one without becomes abstract.
- New items get the new engine. Any single item can still be re-run by hand through `analyse(item)`.
- **Nothing the person made is lost**: kept takes, notes, decisions, and values entered by hand stay.
- Existing explorations stay attached to the same dimension key and keep working in the flower UI.
- When an item is re-run by hand, its old dimensions are matched to the new ones by label and part, and
  matched explorations move across. Unmatched old dimensions stay as "old dimension, not found on this
  item", with their explorations read-only. Nothing is deleted.
- Board `lens_id` / lens JSONs stop driving analysis. Lens files may remain as hints in the board context
  (builder's call), but no lens may force a dimension onto an item.

## 8. Constraints

- Existing stack and patterns (FastAPI + SQLAlchemy + alembic; React canvas). Migrations chain after the
  current head.
- Mock providers must cover every new path so the full suite runs offline, as today.
- `DEMO_MODE` / open-beta guards apply to every new mutating endpoint.
- Engine domain-free guard test extends to the new analysers.

## 9. Decisions made after the builder check (author's calls — the user may override)

- **Dimension value kinds stay.** The analyser assigns each dimension a kind from today's set (enum,
  ordinal, number, color, shape, text). Explore's vocabulary/cleaning, the render check and measurements
  keep working; board-level matching (§4.4) compares label + type + kind.
- **Lens-dependent features.** Vary (already superseded by Explore) is retired: its UI is removed and its
  endpoints return a clear "retired" error; tables stay for history. Explore drops `LENS_REQUIRED` /
  `ATTRIBUTE_NOT_IN_LENS` and works on per-item dimensions. Board profile, validation and retrieval read
  per-item dimensions; retrieval falls back to embeddings when no dimension matches.
- **Render defaults.** Muse Image (image + UI) and a new built-in **Spark rewrite** (text) are available on
  every board without adding them. Board plugins add more renderers; "Connect a renderer" appears only when
  no built-in or added plugin accepts the item. Render goes through the plugin runners, with the built-ins
  registered as plugins.
- **Cost guard without open-beta.** This branch does not wait for open-beta. It adds its own daily
  analysis/render counter per board (same pattern as `DEMO_RUNS_PER_DAY`); when open-beta's budget cap
  lands, the counter defers to it. Flower collapsed state is stored per browser (local storage), not per
  person, until identity exists.

## 10. Left to the builder

- Data model shape for parts/dimensions (extend `ItemAttribute` or add tables), the `ui_screenshot` item
  type vs a sub-kind of `image`, and the migration.
- The free-space placement algorithm, as long as §6.3 holds.
- Exact prompts for analyse/explore; feathering for the composite; check thresholds (keep today's).
- Visual styling, following the source artboards and the current calm-board look.
- Whether lens JSONs survive as context hints.
