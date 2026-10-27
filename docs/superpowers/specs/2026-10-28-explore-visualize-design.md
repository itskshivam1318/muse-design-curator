# Explore → Visualize: text-first variation (design)

Date: 2026-10-28. Status: draft for approval. First of the Phase 1 builds (the agent is out of scope for now).

## Intent

Today "Vary" goes straight to image search: pick an attribute, pick a mode, protect the rest, run, get real photos back. That is good for references but it only shows what already exists in some collection.

The user wants to **explore what is possible** first, in words, and only then spend a visual step on one option. Selecting a watch and exploring "markers" should give options like *Arabic numerals*, *Devanagari numerals*, *only the 12*, *sector dial*, each named and described, before any image is made. The named options become words the user and the model share; this is how the app solves the "I can't say what I want" problem.

Then the user picks one option and visualizes it on their own image, with everything else held fixed.

## What was verified (2026-10-28)

- `POST /v1/images/edits`, multipart, `model=muse-image-1.0`, `image=@<png>`, `prompt=<text>` → HTTP 200, `data[0].b64_json` (webp, 1536×1440 from a 512×486 source). On the Guinand watch photo it changed only the numerals; case, subdials, strap, wrist and watermark were unchanged. A few glyphs were wrong (one numeral stayed Latin), so a check after visualizing is useful.
- `POST /v1/images/generations` (JSON, same model) → HTTP 200, clean product shot.
- Muse Image is listed as not available from India in Meta's Geographic Use Policy §2.2 (last updated 2026-10-12). The user knows, uses it for development, and will swap the model for the demo. The image model must therefore sit behind a swappable provider setting. No region or VPN workarounds.

## Goals

1. From a selected image item and one attribute, get 6–10 **text options** from Muse Spark within a few seconds.
2. Options appear **on the canvas** as cards linked to the source image, so the exploration stays visible and comes back after reload.
3. The user can push the exploration in text: **more**, **further / bolder**, **steer** with a sentence ("only non-Latin scripts"), and **branch** from one option into its own sub-options.
4. **Visualize** one option: an image edit of the source with only that attribute changed. The result lands on the canvas as a new item, linked to the option and the source (lineage line), labelled as generated.
5. After visualizing, **check** the result: the new item is parsed like any other item, then compared against the source: did the target change to the option, did the other attributes stay. Show the outcome as a short verdict on the generated item.
6. Keep **Find real examples** as a second action on an option card: it runs the existing Vary run (search + validator) pointed at that option.

## Non-goals

- The Muse agent and tool parity (later; but every action here is a typed backend endpoint so the agent can call it).
- Exploring several attributes at once (combinations). One attribute per exploration.
- Text-to-image from nothing (generate without a source image). Only edit of an existing item.
- Library panel, chips on canvas, drag-a-dimension gesture, item-as-value, group → common, web fill, new lenses. Each is its own later build (order at the end).

## Anti-goals (would make this a failure even if it works)

- Options that are just the lens vocabulary listed back ("leather, metal, rubber"). Options must be specific, nameable design moves grounded in this image and this board.
- Generating images the user did not ask for. Images are made only on an explicit Visualize click on one option.
- Generated images that look like real photos or licensed sources. They are always labelled "generated" with the model name.
- Losing the old Vary: its search + validation must stay reachable.

## The experience

1. Select an image on the canvas. The toolbar's primary button **Explore** (replaces today's "Vary" label; keyboard `V` stays).
2. The right drawer shows the item's attributes (today's "What to change" list). Click one, for example *Markers: arabic*.
3. An optional one-line steer box ("what direction?") and **Explore**. Muse Spark returns options.
4. Option cards fan out on the canvas next to the source image, joined to it by a thin line. Each card shows:
   - a short name ("Devanagari numerals"),
   - one line on what it looks like,
   - a distance tag: **near** (small step from the current value), **bold**, or **wild**,
   - "keeps: case, hands, strap…" in muted text (the attributes the option assumes stay the same).
5. On the card group: **More** (adds options, no repeats), **Further** (bolder ones), steer box. On a card: **Branch** (sub-options of this one), **Visualize**, **Find real examples**, **Dismiss**.
6. **Visualize** shows a spinner on the card, then a new image item appears beside the card with a "generated · Muse Image" label and a lineage line back to the source. When the check finishes, the item shows a verdict: "Markers → devanagari ✓, 11 of 12 kept" or what drifted.
7. The generated item is a normal board item: Inspect, Explore again, Remove all work on it.

Mock-up of the canvas arrangement (builder may refine):

```
 [source watch] ── ┬─ [Devanagari numerals · bold]  → [generated img]
                   ├─ [Only the 12 · near]
                   ├─ [Sector dial · bold]
                   └─ [Roman numerals · near]   [More] [Further] [steer…]
```

## How it works (decided)

### Backend

- **Explore endpoint**: `POST /api/items/{item_id}/explore` with `{key, steer?, parent_option_id?, mode: "initial"|"more"|"further"}` → creates an exploration (or extends one) and returns its options. Synchronous is fine if Spark answers in under ~30 s; otherwise use the existing job + SSE pattern used by runs (builder's call based on measured latency).
- **Spark call**: Muse Spark 1.3 via the existing `MuseSparkProvider`, with a new structured-output method (for example `explore_options`). Input: the item image, its current attribute values, the attribute spec (label, kind, vocabulary if any), the board title and context, the existing option names (for "more", to avoid repeats), the parent option (for branch), and the steer text. Output per option: `name`, `description`, `distance` (near|bold|wild), `value` (a short canonical token for the attribute, open vocabulary), `keeps` (attribute keys the option leaves alone), `edit_prompt` (the instruction text for the image edit). The mock provider returns deterministic options for tests.
- **Storage**: new tables `explorations` (board, source item, attribute key, steer, created) and `explore_options` (exploration, parent option, name, description, distance, value, keeps, edit_prompt, status: open|dismissed|visualized, x/y on canvas); generated items point back with a new nullable `board_items.explore_option_id`. Alembic migration.
- **Visualize endpoint**: `POST /api/options/{option_id}/visualize` → background job: load the source image (original, not thumb), call the image provider's `edit(image, prompt)`, store the result like an upload, create a `BoardItem` with `origin="generated"`, `rights_status="generated"`, `parent_item_id=source`, link it to the option, then parse it (existing extraction) and run the check. Progress via the existing board events (SSE).
- **Check**: a direct visual question for the target (see decisions below); the validator's comparators for the protected attributes (the option's `keeps`) should match the source. Store a small result on the generated item (`check_json`: target_ok, kept n of m, drifted keys). No retry loop in this build.
- **Image provider**: new provider protocol `ImageProvider.edit(image: bytes, prompt: str) -> bytes`, selected by `IMAGE_PROVIDER` = `muse-image` | `mock` (mock returns the source with a tint, for tests and offline). `IMAGE_MODEL` setting (default `muse-image-1.0`). `.env.example` defaults to `mock`; the user's `.env` sets `muse-image`. Adding another provider later is one class.
- **Find real examples**: builds a `VariationRequest` from the option (mode `prefer`, target value = option value, protected = option `keeps`) and calls the existing run creation. If the attribute's vocabulary is closed and the option's value is not in it, the button is disabled with a hint.
- **Schema changes**: add `"generated"` to `ORIGINS` and `RIGHTS`; adjust the rights check constraint (generated items have no corpus item).
- **Feature flag**: `EXPLORE_ENABLED` (default on). Off → toolbar shows the old Vary.

### Decisions after the builder check (Claude's calls, for the user to check)

- **Values outside a closed vocabulary.** Attributes are soft (Phase 1 doc: "the lens is a starting point, not a schema lock"). Visualizing an option adds its value to the board's lens vocabulary for that attribute if it isn't already there, as a new lens version with origin "explore". So "devanagari" becomes a real value the extractor can return and Find real examples can target.
- **The check asks directly.** The target check does not rely on re-parsing alone. It asks the reasoning provider a direct visual question about the generated image ("Does this show <option name>: <description>? yes/no/unclear, with a box"), and uses the existing comparators only for the kept attributes. The verdict shows the direct answer for the target and "n of m kept" for the rest.
- **All attribute kinds can be explored.** Options are always named design moves in text. The `value` field is typed per kind: a token for enum and text, a number inside min/max for number, a named colour for color, a scale step for ordinal, and the other state for boolean (a boolean exploration gives options about *how*, for example "date window at 6, framed"; value stays the boolean). Shape is excluded while the shape kind is off. Find real examples is enabled only when the value fits the spec after the vocabulary update.
- **What one exploration is.** One exploration per (source item, attribute key). A second Explore, a new steer, More, or Further on that item and attribute all add options to the same exploration (steer is stored per batch). Branch creates sub-options with `parent_option_id` set. More and Further take an optional `parent_option_id` and extend only that branch. The API takes `{key, steer?, parent_option_id?, mode}` and finds or creates the exploration by (item, key). "No repeats" is scoped to the exploration. After a reload, every non-dismissed option of every exploration on the board comes back on the canvas.
- **Provider.** `explore_options` and `check_target` go on the `ReasoningProvider` protocol, implemented by Muse Spark 1.3, Spark Open (Baseten) and the mock. Explore follows `REASONING_PROVIDER`, which is Spark 1.3 in the user's `.env`.
- **Re-visualize.** An option can be visualized more than once. Generated items link to the option through `parent_option_id` on the item, not a single id on the option. Status `visualized` means "at least one image".

### Two places, one list (user's direction, 2026-10-28)

The same options show in two places, kept in sync:

- **In the dimension**: in the drawer, the explored attribute row expands to list its options under it (name, distance tag, one line), with the same actions (Visualize, Branch, Find real examples, Dismiss) and More / Further / steer at the bottom of the list. Branches show indented under their parent option.
- **As notes on the canvas**: each option is also a note card beside the source image, joined by a line. Dismissing, visualizing or adding options in either place updates the other. Hovering an option in the drawer highlights its note on the canvas, and the other way round.

### Frontend

- Option cards are a new canvas node type in react-konva (text card), positioned in a fan next to the source, draggable, saved positions. Lineage lines reuse `lineagePoints`.
- The drawer's Explore panel replaces the Vary panel's step 1 (attribute list) and adds the steer box; the old protect/mode/run steps move behind "Find real examples".
- Generated items render with a "generated · <model>" caption where licensed items show their credit.
- Undo covers dismiss and canvas moves; generating an image is not undone, but the item can be removed.

### Quality bar

Same as the earlier tasks: tests first for backend logic (explore prompt building, option storage, visualize job, check), frontend unit tests for card layout and panel logic, one e2e path with mock providers, code review by subagents per task, final whole-branch review. Work on a new branch `feat/explore-visualize`.

## Constraints

- Muse Spark 1.3 for options; Muse Image only through the provider setting.
- Cost: Muse Image is about $0.01 per image; Spark calls are small. No automatic generation, so no cap needed beyond the existing demo-mode limits (when `DEMO_MODE=1`, visualize requires the passcode unlock).
- Existing tests (558 backend, 109 frontend, 14 extension) must keep passing.

## Left to the builder

- Exact card visuals, fan geometry, and how many cards show before "show all".
- Prompt wording for options and for the edit prompt (start from: "Change only <attribute> to <option>. Keep everything else exactly the same.").
- Sync vs job for the explore call (measure first).

## Later builds (agreed order, each its own design)

1. Home context prompt + Library panel (left: corpus search by text/colour, live open-licence search, drag onto canvas).
2. User-editable attributes everywhere: add / rename / merge / remove; new source labels (read, estimated, web, "?").
3. Attribute chips on the canvas (4–6 per image), clicking a chip starts Explore.
4. Group → what's common (shared / divergent chips, add to vocabulary).
5. Item as a value (drop an item onto an option or attribute).
6. Web fill with citations (Responses API search grounding).
7. Formulation and automobile lenses and demo boards; Baseten split (Spark Open for bulk tagging and verify).
8. Drag-a-dimension gesture (sugar on top of Explore).
