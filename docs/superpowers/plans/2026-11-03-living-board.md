# Living Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the board feel alive. Every image, flower hub, petal, kept take and callout floats in one damped
spring simulation. Nothing overlaps, and flowers always connect to their source. Kept takes stay in their ring
and can be explored further. A floating **+** button adds images.

**Architecture:** A pure physics core (`frontend/src/living/physics.ts`) steps bodies toward *homes*. A home is
either absolute or relative to another body. A pure scene builder (`living/scene.ts`) turns the board's data
(items, explorations, analyses, selection) into body specs and edges, replacing `map/useMap.ts`'s `mapModel` and
`map/layout.ts`'s sweep. A runtime (`living/world.ts`) owns one world per board and a `requestAnimationFrame`
loop. Konva item groups and HTML flowers and callouts read positions *imperatively* each frame, not through
React state. React re-renders only when board data changes. Only homes are stored:
- `board_items.x/y/w/h` (existing);
- new `explorations.dx/dy` (hub offset from its source);
- new `explore_options.undocked`.

**Tech Stack:** React 19, react-konva / Konva 10, TanStack Query, Vitest; FastAPI, SQLAlchemy, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-living-board-design.md` (read it first). The behaviour reference is
`docs/superpowers/specs/2026-11-03-living-board-prototype/living-board.html`. When in doubt about *feel*, match
the prototype.

## Global Constraints

- **Feel constants**, exported as `FEEL` from `living/physics.ts`. Start from these values:
  - drift ±3.2px at 0.55 / 0.42 rad/s, with a random phase per body;
  - damping 0.86 (0.72 when reduced);
  - home spring k: item 0.012, hub 0.035, petal 0.05, kept 0.05, callout 0.09, badge 0.035;
  - invMass: item 0.22, kept 0.45, hub 0.6, petal 1, callout 0.35, badge 0.6;
  - collide gap 14px; 3 positional iterations at 0.3 with a 0.06 velocity kick;
  - grow-in easeOutBack 450 ms (linear 250 ms when reduced);
  - hub lead 260 ms, then petals staggered 70 ms.
- **Ring geometry**, exported from `living/ring.ts`:
  - callout gap {x:105, y:46};
  - hub gap {x:210, y:190};
  - petal arc ±2.35 rad around the hub's direction, radius `max(135, n*19)`;
  - a kept take docks at radius + 30.
- **Take sizes:** docked width 168 (keep the aspect); an undocked take is 300 wide.
- **Reduced motion** (`usePrefersReducedMotion`, already in Canvas):
  - turns off drift, kick and the easeOutBack overshoot;
  - things still glide out of the way.
- **Locked demo** (`readOnly`): item moves behave exactly as today (PATCH items is on the demo open list).
  Hub drags, undocking and the one-time dock-in are applied locally and never written.
- **Never write positions from drift or pushes.** Writes happen only on pointer release, on keep, or in the one-time
  dock-in of old takes.
- **One undo entry per release**, covering items, hubs and docked takes together.
- **Body ids:**
  - items: the item id; a docked take keeps its item id;
  - hubs: `hub:<explorationId>`;
  - petals: `petal:<optionId>`;
  - callouts: `callout:<itemId>:<partKey|whole:item>`.

## Review Focus

1. **Deleting an item that has flowers.** Its hubs, petals and edges must leave the world on the next sync.
   Nothing may be left floating or pointing at a missing parent; a missing `rel` parent falls back to the
   body's last position. Pinned by `physics.test.ts › a body whose parent is gone keeps its place` (Task 2).
2. **An SSE item update arriving mid-drag** (another tab moves the dragged item). The drag must win until
   release, and the stored position must not snap the body back mid-gesture. Pinned by
   `world.test.ts › sync during a grab leaves grabbed bodies where the pointer has them` (Task 4).
3. **Board with no analysis yet, or a failed analysis.** Flowers still draw from the item's bottom edge and
   connect. The hub eases over once the analysis lands, and nothing throws. Pinned by
   `scene.test.ts › a flower whose analysis is missing opens downward and still has a stem` (Task 3).
4. **A tab in the background, or a long frame.** The loop clamps dt so bodies don't explode after the tab
   returns. Pinned by `physics.test.ts › a huge dt is clamped` (Task 2).
5. **A selected item must not drift away from its toolbar or handles.** Selected items are pinned while
   selected. Pinned by `world.test.ts › selected bodies are pinned` (Task 4).

---

### Task 1: Floating + button on the board

**Files:**
- Create: `frontend/src/panels/AddFab.tsx`, `frontend/src/panels/AddFab.test.tsx`
- Modify: `frontend/src/pages/BoardPage.tsx` (render `<AddFab>` with the same handlers as the Library's
  `AddActions`); `frontend/src/shell/BoardShell.tsx` (add an `add?: ReactNode` slot placed right of
  `<BottomToolbar>`); the CSS file that styles `.bottom-toolbar` (`.add-fab`, `.add-fab-pop`)

**Interfaces:**
- Produces: `AddFab({ onFiles, onLink, disabled }: { onFiles: (files: File[]) => void; onLink: (url: string) => Promise<unknown>; disabled?: boolean })`

- [ ] **Step 1: Write the failing tests** in `AddFab.test.tsx`:
  - `opens a popover with the add actions`: click the button named "Add to board", then expect group "Add to board"
    (rendered by `AddActions`) to be visible.
  - `Escape and outside click close it`.
  - `locked: the button is disabled with LOCKED_TITLE`.
  - `a chosen file calls onFiles and closes the popover`.
- [ ] **Step 2: Run them.** `cd frontend && npx vitest run src/panels/AddFab.test.tsx`. Expected: FAIL, because the
  module is missing.
- [ ] **Step 3: Implement `AddFab`.**
  - A 50px round button labelled "+", using `aria-label="Add to board"`, `aria-haspopup="dialog"` and
    `aria-expanded`.
  - It toggles a popover that renders `<AddActions>` unchanged.
  - The "+" rotates 45° when open; there is no rotation under reduced motion.
  - Wire it into `BoardShell` through the new `add` slot.
- [ ] **Step 4: Run the tests.** `npx vitest run src/panels src/shell`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat(board): floating add button beside the tool dock`.

---

### Task 2: Physics core

**Files:**
- Create: `frontend/src/living/physics.ts`, `frontend/src/living/physics.test.ts`

**Interfaces:**
- Produces:
```ts
export type BodyKind = 'item' | 'kept' | 'hub' | 'petal' | 'callout' | 'badge'
export type Home = { kind: 'abs'; x: number; y: number } | { kind: 'rel'; to: string; dx: number; dy: number }
export interface BodySpec {
  id: string; kind: BodyKind; w: number; h: number; home: Home
  /** Where a new body starts (default: its home); e.g. a new hub starts at its anchor. */
  start?: Point
  /** ms after the sync that adds it before it appears (grow-in stagger). */
  delay?: number
  /** Skip collisions with this body id (a callout with its own item). */
  ignore?: string
}
export interface Body extends BodySpec { x: number; y: number; vx: number; vy: number; bornAt: number; pulseAt: number; pinned: boolean; ph1: number; ph2: number }
export interface World { bodies: Map<string, Body> }
export const FEEL: { drift: number; driftW: [number, number]; damp: number; dampReduced: number; k: Record<BodyKind, number>; invMass: Record<BodyKind, number>; gap: number; iterations: number; push: number; kick: number; growMs: number; hubLeadMs: number; petalStaggerMs: number } // Global Constraints values
export function createWorld(): World
export function syncWorld(w: World, specs: BodySpec[], now: number, rng?: () => number): void
export function homeOf(w: World, b: Body): Point
export function stepWorld(w: World, dtFrames: number, now: number, opts: { reduced: boolean }): void
export function growScale(b: Body, now: number, reduced: boolean): number   // 0..~1.1, includes the keep swell
```
  Positions are **centres**.
  - `syncWorld` adds new bodies, updates the spec fields of existing bodies (keeping x/y/v), and removes missing
    ones.
  - Bodies whose `growScale < 0.25` don't collide.
  - Pinned bodies have infinite mass and skip springs.
  - `stepWorld` clamps `dtFrames` to [0, 3].
  - `homeOf` for a `rel` home whose parent is missing returns the body's current position.

- [ ] **Step 1: Write the failing tests:**
  - `a lone body springs to its abs home` (start 200px away, 600 steps, reduced: true → within 0.5px).
  - `a rel home follows its parent` (move parent's home; child settles at parent + dx/dy).
  - `two overlapping bodies separate by at least the gap` (2 items at the same home, 600 steps → `|dx| >= (w1+w2)/2 + 14 - 1` or the same for dy).
  - `a pinned body does not move and pushes a petal out`.
  - `drift stays within FEEL.drift of home at rest` (reduced: false, sample 300 steps after settling).
  - `reduced motion: at rest exactly at home` (≤0.01px).
  - `a body not yet born neither moves others nor is drawn` (`growScale` 0 before `bornAt + delay`).
  - `a body whose parent is gone keeps its place`.
  - `a huge dt is clamped` (`stepWorld(w, 1000, …)` leaves every coordinate finite and within 500px of home).
  - `sync keeps positions of bodies that stay and removes the rest`.
- [ ] **Step 2: Run them.** `npx vitest run src/living/physics.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement the engine.** Follow the prototype's `step()`. Collision is a rectangle with gap, resolved
  along the axis of smaller overlap, with the push split by invMass. Use an O(n²) loop over awake bodies; the
  board is around 150 bodies.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat(living): damped spring physics core with homes, collisions and drift`.

---

### Task 3: Ring geometry and the scene builder

**Files:**
- Create: `frontend/src/living/ring.ts`, `frontend/src/living/ring.test.ts`, `frontend/src/living/scene.ts`,
  `frontend/src/living/scene.test.ts`
- Modify: `frontend/src/map/cards.ts`. Export `calloutSize(item, analysis, card, forms=0): { w: number; h: number }`
  (w = `CALLOUT_W`, h from the existing `cardHeight`). Delete `calloutBounds`.
- Modify: `frontend/src/api.ts`:
  - `Exploration` gets `dx: number | null; dy: number | null`;
  - `ExploreOption` gets `undocked: boolean`.

**Interfaces:**
- Consumes: `BodySpec`, `Home` (Task 2); `partAnchor` (`map/regions.ts`); `optionTree` (`explore/logic`);
  `isKept` (`map/results`).
- Produces:
```ts
// ring.ts
export const CALLOUT_GAP = { x: 105, y: 46 }, HUB_GAP = { x: 210, y: 190 }, PETAL_ARC = 2.35, KEPT_EXTRA = 30
export const DOCKED_W = 168, UNDOCKED_W = 300
export function ringAngles(owner: { w: number; h: number }, anchors: (Point | null)[]): number[] // anchors relative to owner centre; null = whole item (prefers π/2)
export function ellipsePoint(owner: { w: number; h: number }, angle: number, gap: { x: number; y: number }): Point
export function petalAngles(dir: number, n: number): number[]
export const petalRadius = (n: number) => Math.max(135, n * 19)
export function dockedSize(s: { w: number; h: number }): { w: number; h: number }
export function undockedSize(s: { w: number; h: number }): { w: number; h: number }
// scene.ts
export interface FlowerModel { id: string; hubId: string; sourceId: string; key: string; label: string; part: string | null; options: ExploreOption[]; collapsed: boolean }
export type EdgeEnd = { body: string; anchor?: { fx: number; fy: number } }   // no anchor: the point where the body's edge faces the other end
export interface Edge { id: string; kind: 'stem' | 'leader' | 'spoke'; from: EdgeEnd; to: EdgeEnd; kept?: boolean }
export interface Scene { specs: BodySpec[]; edges: Edge[]; flowers: FlowerModel[]; docked: Map<string, { optionId: string; hubId: string }> } // docked: take item id → its ring
export interface SceneInput {
  items: readonly Item[]; explorations: readonly Exploration[]
  analyses: ReadonlyMap<string, AnalysisView | null | undefined>; labels: ReadonlyMap<string, string>
  collapsed: (explorationId: string) => boolean; selectedId: string | null
  formsOn?: (card: string) => number
}
export function buildScene(input: SceneInput): Scene
```
Rules (`buildScene`):
- **Items.** Every board item becomes `kind:'item'` with an `abs` home at its centre, except docked takes.
- **Docked takes.** A take is docked when it is un-staged, it is some option's `kept_item_id`, and that option is not
  `undocked`. It becomes `kind:'kept'`. Its size is the item's stored w/h. Its home is `rel` to the hub, at
  `petalRadius(n) + KEPT_EXTRA` along the option's petal angle.
- **Hubs.**
  - A hub's home is `rel` to its source item: `(dx, dy)` when stored. Otherwise the offset is
    `ellipsePoint(source, angle, HUB_GAP)`, where `angle` is the `ringAngles` slot of the dimension's card
    (`cardOf`). With no analysis, the angle is π/2.
  - A hub starts at the anchor and has `delay: 0`. Its petals have `delay: FEEL.hubLeadMs + i*FEEL.petalStaggerMs`.
  - A collapsed flower becomes one `badge` body (120×28) instead of the hub and its petals. Its docked takes keep
    their `rel` homes, at radius 70.
- **Petals.** Each option not dismissed and not kept becomes a petal 88×88 with a `rel` home on the hub ring.
- **Callouts.** These exist only for `selectedId`, one per card. The home is `rel` to the item at
  `ellipsePoint(item, ringAngles slot, CALLOUT_GAP)`, with `ignore` set to the item id.
- **Edges.**
  - Every flower has a stem from its source to the hub. The source end is anchored at the part anchor as a
    fraction; a whole-item dimension uses the edge point instead.
  - When the source is selected, the stem becomes a leader (source anchor → callout) plus a stem (callout → hub).
  - A spoke runs from the hub to each petal, and one to each docked take (`kept: true`).

- [ ] **Step 1: Write the failing tests.**
  - `ring.test.ts`:
    - `ringAngles spreads anchors that all sit below the item` (5 anchors with dy>0 → pairwise angular gap ≥ 2π/5 − 1e-6);
    - `ringAngles keeps a single right anchor at angle 0`;
    - `dockedSize keeps the aspect at 168 wide`.
  - `scene.test.ts`, using the same fixtures as `map/useMap.test.ts` (move the reusable ones):
    - `a flower's hub is rel to its source with the stored dx/dy`;
    - `without dx/dy the hub sits at the callout slot angle`;
    - `a flower whose analysis is missing opens downward and still has a stem`;
    - `a kept take is docked: kind kept, rel to its hub, and no petal for its option`;
    - `an undocked take is an ordinary item`;
    - `callouts only for the selected item, and its stems route through them`;
    - `a collapsed flower is one badge and its docked takes stay`;
    - `a take of a kept option nested on a docked take gets its own flower`. A docked take's id is the source of a
      further exploration; its hub is `rel` to the take.
- [ ] **Step 2: Run them.** `npx vitest run src/living`. Expected: FAIL.
- [ ] **Step 3: Implement `ring.ts` and `scene.ts`.** Port `ringAngles` from the prototype.
- [ ] **Step 4: Run the tests.** Expected: PASS. `npx tsc -b` must be clean; this fails for any caller of the deleted
  `calloutBounds`. Leave `useMap` compiling by keeping its old import until Task 5. If you have to, inline
  `calloutBounds` into `useMap` temporarily, then delete it in Task 5.
- [ ] **Step 5: Commit.** Message: `feat(living): ring geometry and scene builder (bodies, homes, edges)`.

---

### Task 4: Runtime world, frame loop and drag API

**Files:**
- Create: `frontend/src/living/world.ts`, `frontend/src/living/world.test.ts`,
  `frontend/src/living/useLiving.tsx`

**Interfaces:**
- Consumes: Task 2 and Task 3 exports.
- Produces:
```ts
export interface LivingWorld {
  sync(scene: Scene, now?: number): void
  body(id: string): Body | undefined
  /** Called after each step (one rAF); returns unsubscribe. */
  onFrame(fn: (now: number) => void): () => void
  setPinned(ids: Iterable<string>): void         // replaces the pinned set (selection)
  grab(ids: string[]): void                      // grabbed bodies are pinned and follow dragBy
  dragBy(dx: number, dy: number): void           // moves every grabbed body by the delta since grab
  release(): Map<string, Point>                  // grabbed ids → centres at release; ungrabs
  pulse(id: string): void                        // the keep swell / "already open" nudge
  setReduced(r: boolean): void
  start(): void; stop(): void
}
export function createLivingWorld(opts: { reduced: boolean; now?: () => number; schedule?: (cb: FrameRequestCallback) => number; cancel?: (h: number) => void }): LivingWorld
// useLiving.tsx
export const LivingProvider: React.FC<{ world: LivingWorld; children: ReactNode }>
export function useLivingWorld(): LivingWorld
/** Writes `transform` (translate to top-left + grow scale) and opacity onto ref.current every frame. */
export function useBodyElement(id: string, ref: RefObject<HTMLElement | null>): void
```
  - The loop runs only while started.
  - Sleep: bodies more than one viewport-diagonal outside the viewport are not stepped. Add
    `setViewport(b: Bounds)` to the interface for this.
  - `sync` must not move grabbed bodies.

- [ ] **Step 1: Write the failing tests** (fake `now` and `schedule`):
  - `sync during a grab leaves grabbed bodies where the pointer has them`;
  - `dragBy moves every grabbed body by the same delta`;
  - `release returns centres and unpins`;
  - `selected bodies are pinned` (`setPinned`; stepping leaves them exactly put while a neighbour is pushed);
  - `onFrame subscribers run once per scheduled frame and stop after stop()`;
  - `offscreen bodies sleep`.
- [ ] **Step 2: Run them.** `npx vitest run src/living/world.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat(living): runtime world with frame loop, pinning and drag API`.

---

### Task 5: Items, flowers and callouts drawn from the world

This is the integration task. After it, the board floats.

**Files:**
- Modify: `frontend/src/canvas/Canvas.tsx`:
  - create the world (`createLivingWorld({ reduced })`) once per board and wrap the overlays in `LivingProvider`;
  - build the scene with `buildScene` from the data `useMap` gathers today (move the analyses `useQueries` and
    collapsed subscription into `useLivingScene`);
  - call `world.sync(scene)` in an effect;
  - `world.setPinned(selected)`;
  - `world.setViewport(viewport)`.
- Create: `frontend/src/living/useLivingScene.ts`, which replaces `map/useMap.ts`. Delete `useMap.ts` and
  `useMap.test.ts`; move the still-meaningful tests into `scene.test.ts`.
- Create: `frontend/src/living/useKonvaBodies.ts`:
  - each frame, set every `item`/`kept` Konva group's position to the body's top-left and scale to `growScale`
    (`layer.findOne('#' + id)`), then `layer.batchDraw()`;
  - the hover outline, status dot and lineage lines that Canvas draws from `item.x/y` must read the live body
    instead. Use a small `useLiveBounds(id)` that re-renders at most once per frame, and only for the hovered and
    selected items.
- Create: `frontend/src/living/Edges.tsx`. One `<svg>` in canvas units. Each frame it writes `d` on a `<path>` per
  edge: a cubic for a stem, a quadratic for a spoke, with the bend clamped (±40 stem, ±22 spoke) from relative
  velocity, as in the prototype. It also draws an anchor dot r=4.5/scale at the stem source. Spokes for kept takes
  are green, solid and 1.6× wide.
- Modify: `frontend/src/map/Flower.tsx`:
  - the hub, petals and badge each get `useBodyElement` instead of `left/top` from `FlowerLayout`;
  - remove the inline `<svg className="flower-lines">`, since Edges draws them;
  - `keepAt` is replaced in Task 7, so leave it compiling via a temporary `placeBeside` import until then.
- Modify: `frontend/src/map/Callouts.tsx`: each card is positioned by `useBodyElement('callout:…')`. Delete the
  `calloutSlots` layout use.
- Modify: `frontend/src/map/layout.ts`: delete `calloutSlots`, `layoutFlowers`, `placeFlower`, `visibleFlowers`,
  `sweep` and `build`, along with their tests. Keep `clampCard` and `placeBeside` (until Task 7).
- Modify: the item drag in `Canvas.tsx` handlers:
  - `onDragStart` → `world.grab(picked)`;
  - `onDragMove` → `world.dragBy(dx, dy)`, with no more `setOverrides` per move;
  - `onDragEnd` → `world.release()`, then `actions.move(moves)` exactly as today.
  - The node-drop path is unchanged.

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `useLivingScene(boardId, items, selectedId): Scene`;
  - `useKonvaBodies(world, layerRef)`;
  - `<Edges scene view />`;
  - `useLiveBounds(id): Bounds | null`.

- [ ] **Step 1: Update tests first.**
  - Canvas and Flower tests that asserted `left/top` from layouts now assert that a hub element exists for each
    flower and that `Edges` renders one stem per flower. Assert stems both with and without a selection; this is
    the "always connected" requirement.
  - Add `Canvas.test.tsx › flowers stay connected when nothing is selected` (one `path[data-edge-kind="stem"]`
    per flower, with no selection).
- [ ] **Step 2: Run them.** `npx vitest run src/canvas src/map src/living`. Expected: the new assertions FAIL.
- [ ] **Step 3: Implement the wiring above.**
- [ ] **Step 4: Run all frontend tests and the type check.** `npx vitest run && npx tsc -b && npm run lint`.
  Expected: PASS.
- [ ] **Step 5: Manual check** (`make dev`, open the "cars" board):
  - things drift;
  - dragging a car pushes others and its flowers follow;
  - nothing overlaps at rest;
  - stems reach the car with nothing selected;
  - callouts ring the selected car.
- [ ] **Step 6: Commit.** Message: `feat(living): board items, flowers and callouts float in one world`.

---

### Task 6: Hub offsets (backend + drag) and the release commit

**Files:**
- Create: `backend/alembic/versions/0009_living_board.py`:
  - `explorations.dx`, `explorations.dy` (Float, nullable);
  - `explore_options.undocked` (Boolean, not null, server_default "0").
- Modify:
  - `backend/app/db/models.py`: add the columns.
  - `backend/app/db/repos/explore.py`: serialize `dx`, `dy` in `exploration_to_dict` and `undocked` in
    `option_to_dict`.
  - `backend/app/api/explore.py`: add `PATCH /api/explorations/{exploration_id}` with body
    `{dx: float, dy: float}`. It returns the exploration dict and publishes the exploration update the way
    `service.update_option` does (`publish_later`). It is **not** on the demo open list.
  - `OptionPatch`: add `undocked: bool | None`.
- Test: `backend/tests/integration/api/test_explorations_patch.py`
- Modify:
  - `frontend/src/api.ts`: `patchExploration(id, { dx, dy })`.
  - `frontend/src/canvas/history.ts`: no new kind. Use `pushRevert`.
- Create: `frontend/src/living/release.ts`, `frontend/src/living/release.test.ts`
- Modify: `Flower.tsx`. The hub gets `onPointerDown` → `world.grab([hubId])`, moves → `dragBy`, and up →
  `commitRelease`.

**Interfaces:**
```ts
// release.ts (pure)
export interface ReleasePlan {
  moves: Move[]                                                    // item top-left moves (incl. docked takes carried along)
  hubs: { explorationId: string; from: { dx: number; dy: number } | null; to: { dx: number; dy: number } }[]
  dock: { optionId: string; itemId: string; undocked: boolean; size: { w: number; h: number }; from: { w: number; h: number } }[]
}
export function planRelease(scene: Scene, items: readonly Item[], explorations: readonly Exploration[], released: ReadonlyMap<string, Point>, homeAfter: (id: string) => Point): ReleasePlan
// actions.ts
commitRelease(plan: ReleasePlan, opts: { locked: boolean }): void   // one history entry; locked → local cache only
```
  - `homeAfter` resolves a body's home with the released centres applied. Docked takes reachable from a released
    body (source → hub → take, transitively) get a move to their new slot's top-left.
  - `commitRelease` applies everything optimistically to the query caches, writes everything (PATCH items,
    exploration, option), and pushes a single `pushRevert` that applies the inverse.

- [ ] **Step 1: Write the failing backend test.** It covers: PATCH sets dx/dy and GET returns them; 404 for an
  unknown id; 403 `DEMO_LOCKED` in locked demo mode; `undocked` round-trips through PATCH `/options/{id}`. Also
  write a migration test in the existing migration-test style, or extend it if there is one: upgrade to 0009
  from 0008 on a db with rows.
- [ ] **Step 2: Run it.** `cd backend && uv run pytest tests/integration/api/test_explorations_patch.py -q`.
  Expected: FAIL.
- [ ] **Step 3: Implement the backend.** Run it again: PASS. Then run the full suite: `uv run pytest -q`.
- [ ] **Step 4: Write the failing frontend tests** in `release.test.ts`:
  - `dragging a source moves its docked takes too`;
  - `dragging a hub records from/to offsets`;
  - `dragging a docked take beyond one ring radius undocks it at full size`;
  - `dropping an undocked take near its slot docks it at docked size`.
  - In `actions.test.tsx`: `commitRelease is one undo step` and `locked commitRelease writes nothing`.
- [ ] **Step 5: Implement.** Run `npx vitest run`. Expected: PASS.
- [ ] **Step 6: Commit.** Two commits:
  - `feat(explore): hub offsets and undocked flag (migration 0009)`
  - `feat(living): drag flower hubs; one undoable write per release`

---

### Task 7: Kept takes live in their ring

**Files:**
- Modify:
  - `backend/app/api/explore.py` `KeepBody`: add `w`, `h` (optional, > 0).
  - `backend/app/explore/keep.py` `keep_take(..., size: tuple[float, float] | None = None)`: writes `w/h` when given
    and sets `undocked=False`.
  - Test: extend `backend/tests/integration/api/test_keep.py` with `keep with a size writes w and h` and
    `keep re-docks an undocked option`.
- Modify:
  - `frontend/src/api.ts`: `keepTake(optionId, itemId, at?, size?)`.
  - `frontend/src/map/Flower.tsx`: `keepAt` now returns the docked slot's top-left and `dockedSize(take)`, computed
    from `world.body(hubId)` and ring.ts. Remove `placeBeside`.
  - `map/PetalCard.tsx`: pass the size through and patch the cache with `{x, y, w, h, staged:false}`. After keep,
    `world.pulse(takeId)`.
- Modify: `frontend/src/map/layout.ts`: delete `placeBeside` and its tests.
- Create: `frontend/src/living/dockIn.ts`, `frontend/src/living/dockIn.test.ts`.

**Interfaces:**
```ts
// dockIn.ts (pure) — the one-time move of takes kept before this shipped
export function staleDocked(scene: Scene, items: readonly Item[], slotOf: (itemId: string) => Point): { id: string; x: number; y: number; w: number; h: number }[]
```
  - A docked take is stale when its stored width differs from `dockedSize(it).w` by more than 1px.
  - The Canvas runs it once per board load, after the world has settled for 1 s. It PATCHes each stale take's
    `{x, y, w, h}` with no undo entry. It is skipped when locked.

- [ ] **Step 1: Write the failing tests:**
  - backend keep tests (above);
  - `dockIn.test.ts`: `a full-size kept take is stale`, `a docked-size take is not`, `undocked takes are never stale`;
  - `Flower.test.tsx`: `keep sends the docked size and slot`;
  - `Canvas.test.tsx`: `a docked take selected shows its callouts and its dimensions open a flower from it`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** `uv run pytest -q` and `npx vitest run && npx tsc -b`. Expected: PASS.
- [ ] **Step 5: Manual check on "cars".**
  - The old green and yellow takes move into their rings once.
  - A new keep stays in its ring.
  - Click the take, open a dimension: a flower grows from it.
  - Drag the take out: it grows to full size and stays.
  - Drag it back: it docks.
- [ ] **Step 6: Commit.** Message: `feat(living): kept takes dock in their ring and explore further from there`.

---

### Task 8: Life on creation, and the end-to-end pass

**Files:**
- Modify:
  - `living/useKonvaBodies.ts` and `useBodyElement`: apply `growScale` and opacity `min(1, scale*1.6)`, which
    already exists from Task 2. Make sure *new* items added by upload or paste grow in, and the neighbours make room.
  - `Callouts.tsx`: callouts are staggered 45 ms.
  - `Canvas.tsx` `openDimension`: when a flower already exists, call `world.pulse(hubId)` instead of only
    un-collapsing it.
- Modify: `frontend/tests/e2e/map.spec.ts`. The selectors that relied on fixed flower positions now wait for
  `[data-exploration-id]` to be visible. Add `stems connect with nothing selected` (count `path[data-edge-kind="stem"]`
  ≥ the number of flowers) and `the add button uploads an image`.
- Modify: `README.md` board section. Add one paragraph: the board floats, positions are homes, and drift is never
  saved.

- [ ] **Step 1: Write the failing tests:**
  - `physics.test.ts`: `growScale follows easeOutBack and the keep swell decays within 700 ms`;
  - `Canvas.test.tsx`: `opening an existing dimension pulses its hub`;
  - the e2e additions above.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full verification:**
  - `make test`
  - `make lint`
  - `cd frontend && npx vitest run`
  - `make e2e`, twice; it must be green both times.
  - Expected: all PASS.
- [ ] **Step 5: Manual check with reduced motion on.** Turn on macOS → Accessibility → Display → Reduce motion.
  Expected: no drift or bounce, things still glide aside, and no overshoot on grow-in.
- [ ] **Step 6: Commit.** Message: `feat(living): grow-in, keep swell and e2e coverage`.
