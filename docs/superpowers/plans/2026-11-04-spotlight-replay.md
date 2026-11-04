# Spotlight Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a finished agent run, "Show me how" plays the run's highlighted steps over the live board: dim it, light up the items each step touched, a card with the step's `say` and number, Next / Back.

**Architecture:** Frontend only; the steps API already carries `highlight`, `ok`, `say`, `turn` and `item_ids`. A small shared store (`shell/spotlight.ts`, same pattern as `shell/tools.ts`) holds the replay; the agent card starts it; the canvas reads it, pans to the lit items and draws `SpotlightLayer` (dim with cut-outs plus the caption card) in screen space like its other overlays. A `?replay=<run_id>` link opens a replay on load, for the landing page.

**Tech Stack:** React 19, TypeScript, TanStack Query, Vitest + Testing Library (`npm test`), oxlint (`npm run lint`), `tsc -b` (`npm run build`).

**Spec:** `docs/superpowers/specs/2026-11-03-board-agent-design.md` — §"What it is" (spotlight bullet), Goal 6, anti-goal "A tour that hides the board", §4 "Spotlight replay (A)", §8 (locked visitors can watch the replay), "Calls I made" (the panel lists past runs, spotlight replays one run at a time).

## Global Constraints

- It replays recorded steps; it does not re-run tools (no API writes while replaying).
- Spotlight must leave the board readable: the dim is translucent, never opaque; it is a replay of real work, not an app tutorial.
- Highlights are the agent's `highlight: true`, togglable in the panel (the star; already built).
- Locked demo visitors can watch the replay and look around, and nothing more (no star toggling, no run start).
- Spotlight replays one run at a time; the panel lists past runs.
- Copy is plain and short, as in the rest of the board UI: button `Show me how`; card buttons `Back`, `Next`, `Done` (on the last step), close `×` with `aria-label="Close replay"`; counter `{n} of {m}`.
- Work on a branch `feat/spotlight-replay` in a worktree. Another session is building an in-app chat box in `frontend/src/shell/` next to `AgentCard`: keep `AgentCard.tsx` edits to the run picker and the button, and rebase on main before merging.

## Rulings (made while planning; the person can overturn)

- **Which steps play:** highlighted steps that succeeded (`highlight && ok`), in turn order. Refused steps are left out: on the recorded boards a refused call is usually retried with the same `say`, so it would show the same card twice.
- **When the button shows:** the shown run has status `done` and at least one step to play. ("On a finished run.")
- **What is lit:** the step's `item_ids` that are still on the board. The view pans and zooms to fit them (`fitView`, never zooming in past 1).
- **The board under the dim** stays live (items keep moving with the physics) and can still be panned and zoomed; clicks on the canvas pass through the dim.

## Review Focus

1. A lit item that was removed from the board since (the room's removed duplicate, an old sheet's notes): the card shows centred with `This step's pictures are no longer on the board.`, nothing is cut out, Next still works. → Task 3 test `shows the card centred when the step's items are gone`.
2. A step that touched many items (eight uploads, a sheet of nine): every present item is cut out and the view fits all of them, not just the first. → Task 3 test `cuts out every present item` and Task 4 test `fits the view to all lit items`.
3. Keys during a replay: `Escape` closes the replay only (the selection and an open rail are left alone), `ArrowRight`/`ArrowLeft` step; typing in an input is not hijacked. → Task 3 tests `Escape closes only the replay`, `arrow keys step`, `keys typed in an input are left alone`.
4. A locked demo visitor: sees `Show me how` and can replay; the star stays hidden. → Task 2 test `a locked visitor can still replay`.
5. A run whose highlighted steps all failed, or that is still running: no button. → Task 1 test `leaves out refused and unstarred steps`, Task 2 test `no button while the run is open or has nothing to play`.

---

### Task 1: The replay store

**Files:**
- Create: `frontend/src/shell/spotlight.ts`
- Test: `frontend/src/shell/spotlight.test.ts`

**Interfaces:**
- Consumes: `AgentStep` from `../api`.
- Produces:
  - `replaySteps(steps: AgentStep[]): AgentStep[]` — `highlight && ok`, sorted by `turn`.
  - `interface Spotlight { runId: string; steps: AgentStep[]; index: number }`
  - `spotlightStore` with `get(): Spotlight | null`, `subscribe`.
  - `startSpotlight(runId: string, steps: AgentStep[]): void` — stores `replaySteps(steps)` at index 0; does nothing if that list is empty.
  - `nextSpot(): void` — index + 1; past the last step it closes.
  - `backSpot(): void` — index − 1, not below 0.
  - `closeSpotlight(): void`
  - `useSpotlight(): Spotlight | null` (`useSyncExternalStore`).
  - `currentStep(s: Spotlight | null): AgentStep | null`

- [ ] **Step 1: Write the failing tests** (use `makeStep` from `../test/fixtures`; reset with `closeSpotlight()` in `afterEach`)

```ts
it('leaves out refused and unstarred steps, in turn order', () => {
  const steps = [
    makeStep({ id: 's3', turn: 3, highlight: true, ok: true }),
    makeStep({ id: 's1', turn: 1, highlight: true, ok: false }),
    makeStep({ id: 's2', turn: 2, highlight: false, ok: true }),
    makeStep({ id: 's0', turn: 0, highlight: true, ok: true }),
  ]
  expect(replaySteps(steps).map((s) => s.id)).toEqual(['s0', 's3'])
})

it('steps forward and back, and closes past the last step', () => {
  startSpotlight('r1', [makeStep({ id: 'a', turn: 1, highlight: true }), makeStep({ id: 'b', turn: 2, highlight: true })])
  expect(currentStep(spotlightStore.get())?.id).toBe('a')
  backSpot()
  expect(spotlightStore.get()?.index).toBe(0)
  nextSpot()
  expect(currentStep(spotlightStore.get())?.id).toBe('b')
  nextSpot()
  expect(spotlightStore.get()).toBeNull()
})

it('does not start with nothing to play', () => {
  startSpotlight('r1', [makeStep({ highlight: false })])
  expect(spotlightStore.get()).toBeNull()
})
```

- [ ] **Step 2: Run** `npx vitest run src/shell/spotlight.test.ts` — expect FAIL (module not found).
- [ ] **Step 3: Implement** `spotlight.ts` with the store pattern of `shell/tools.ts` (`createStore`, `useSyncExternalStore`).
- [ ] **Step 4: Run** the same command — expect PASS.
- [ ] **Step 5: Commit** `feat(spotlight): the replay store`

---

### Task 2: Past runs and "Show me how" in the agent card

**Files:**
- Modify: `frontend/src/shell/AgentCard.tsx` (`useLatestRun` → `useRun(boardId, chosenId)`; a run picker; the button)
- Test: `frontend/src/shell/AgentCard.test.tsx`

**Interfaces:**
- Consumes: Task 1's `replaySteps`, `startSpotlight`, `useSpotlight`.
- Produces: nothing new for later tasks; Task 5 adds the `?replay=` start here.

Behaviour:
- The card shows the latest run unless the person picked another. In the expanded view, when the board has more than one run, a `<select aria-label="Run">` lists the runs newest first, each labelled `{agentName} · {goal cut to 40 chars}` with the run id as value. Picking one shows its goal, deliverables and steps. A newer run starting does not change a pick the person made.
- `Show me how` (a button in the expanded run view, under the deliverables, and in the collapsed card next to the latest line) shows when the shown run's status is `done` and `replaySteps(steps)` is not empty. It calls `startSpotlight(run.id, steps)`. It is shown when the board is locked.
- While a replay is on, the card collapses (it would cover the board) and its button reads `Replaying…` and is disabled.

- [ ] **Step 1: Write the failing tests** (extend `renderCard` to accept `runs?: AgentRun[]` and per-run steps)

```ts
it('shows Show me how on a finished run with starred steps', async () => {
  renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
  fireEvent.click(screen.getByRole('button', { name: 'Show me how' }))
  expect(spotlightStore.get()?.runId).toBe('r1')
})

it('no button while the run is open or has nothing to play', () => {
  renderCard({ run: makeRun({ status: 'running' }), steps: [makeStep({ highlight: true })] })
  expect(screen.queryByRole('button', { name: 'Show me how' })).toBeNull()
  cleanup()
  renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true, ok: false })] })
  expect(screen.queryByRole('button', { name: 'Show me how' })).toBeNull()
})

it('a locked visitor can still replay', () => {
  renderCard({ locked: true, run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
  expect(screen.getByRole('button', { name: 'Show me how' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
  expect(screen.queryByRole('button', { name: 'Highlight step' })).toBeNull()
})

it('lists past runs and replays the one picked', () => {
  // two runs, newest first: r2 (running), r1 (done, one starred step)
  // expand, choose r1 in the Run select: its goal shows and Show me how starts r1
})
```

- [ ] **Step 2: Run** `npx vitest run src/shell/AgentCard.test.tsx` — expect the new tests to FAIL.
- [ ] **Step 3: Implement.** Keep the pick in `useState<string | null>(null)`; the shown run is `runs.find(r => r.id === pick) ?? runs[0]`. Fill in the last test's body to match.
- [ ] **Step 4: Run** the same command — expect PASS (old tests too).
- [ ] **Step 5: Commit** `feat(spotlight): past runs and Show me how in the agent card`

---

### Task 3: The spotlight layer

**Files:**
- Create: `frontend/src/canvas/SpotlightLayer.tsx`
- Modify: `frontend/src/shell/shell.css` for `.spotlight-dim` and `.spotlight-card`
- Test: `frontend/src/canvas/SpotlightLayer.test.tsx`

**Interfaces:**
- Consumes: Task 1's `Spotlight`, `currentStep`, `nextSpot`, `backSpot`, `closeSpotlight`; `Bounds` from `./geometry`.
- Produces: `SpotlightLayer({ spotlight, lit, size }: { spotlight: Spotlight; lit: Bounds[]; size: { width: number; height: number } })` — `lit` is the screen bounds of the step's present items (the canvas computes them, Task 4).

Behaviour:
- An SVG over the stage, `pointer-events: none`: one path with `fill-rule="evenodd"`, the full stage rect plus a rounded rect (8 px padding) per lit bound, fill `rgba(20, 18, 16, 0.45)`.
- The card (`role="dialog"`, `aria-label="Replay"`, `pointer-events: auto`): `Step {turn}` small above the `say` (or the tool name when `say` is empty), `{index+1} of {count}`, `Back` (disabled on the first), `Next` (`Done` on the last), `×` (`aria-label="Close replay"`). It sits under the union of `lit` if there is room in `size`, else above it, else centred; with `lit` empty it is centred and adds `This step's pictures are no longer on the board.`
- Keys (a `keydown` listener on `window` in the capture phase, removed on unmount): `Escape` → `closeSpotlight()`, `ArrowRight` → `nextSpot()`, `ArrowLeft` → `backSpot()`, each with `stopImmediatePropagation()` and `preventDefault()`; skipped when `isTyping(e.target)` (from `../pages/shortcutGuard`).
- Focus moves to `Next` when the layer mounts.

- [ ] **Step 1: Write the failing tests**

```ts
it('cuts out every present item', () => {
  const { container } = render(<SpotlightLayer spotlight={spot} lit={[b(10, 10), b(200, 10), b(400, 10)]} size={{ width: 1000, height: 700 }} />)
  const d = container.querySelector('path.spotlight-dim')!.getAttribute('d')!
  expect(d.match(/M/g)).toHaveLength(4) // the stage and three holes
})

it("shows the card centred when the step's items are gone", () => {
  render(<SpotlightLayer spotlight={spot} lit={[]} size={{ width: 1000, height: 700 }} />)
  expect(screen.getByText("This step's pictures are no longer on the board.")).toBeTruthy()
})

it('shows the say, the step number and the count; Back is off on the first', () => {
  // spot: two steps, turn 12 say "Rendering the anchor room." first
  expect(screen.getByText('Rendering the anchor room.')).toBeTruthy()
  expect(screen.getByText('Step 12')).toBeTruthy()
  expect(screen.getByText('1 of 2')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Back' }) as HTMLButtonElement).disabled).toBe(true)
})

it('Escape closes only the replay', () => {
  const other = vi.fn()
  window.addEventListener('keydown', other)
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(spotlightStore.get()).toBeNull()
  expect(other).not.toHaveBeenCalled()
})

it('arrow keys step', () => { /* ArrowRight → index 1; ArrowLeft → index 0 */ })

it('keys typed in an input are left alone', () => {
  // an <input> in the document has focus; ArrowRight on it leaves the index at 0
})

it('says Done on the last step and closes', () => { /* index 1 of 2: button "Done"; click → store null */ })
```

`spot` comes from `startSpotlight` in a `beforeEach`; the layer reads its `spotlight` prop, but the tests drive the store and re-render with `useSpotlight()` through a small wrapper.

- [ ] **Step 2: Run** `npx vitest run src/canvas/SpotlightLayer.test.tsx` — expect FAIL.
- [ ] **Step 3: Implement** the layer and its CSS (card in the existing card style: the agent card's background, radius and shadow).
- [ ] **Step 4: Run** the same command — expect PASS.
- [ ] **Step 5: Commit** `feat(spotlight): the dim, the cut-outs and the caption card`

---

### Task 4: The canvas follows the replay

**Files:**
- Modify: `frontend/src/canvas/Canvas.tsx` (read `useSpotlight()`; pan on step change; render `SpotlightLayer` last among the overlays)
- Modify: `frontend/src/canvas/geometry.ts` only if a helper is needed
- Test: `frontend/src/canvas/Canvas.test.tsx` (follow its setup)

**Interfaces:**
- Consumes: Task 1 `useSpotlight`, `currentStep`; Task 3 `SpotlightLayer`; existing `fitView`, `itemBounds`, `toScreenBounds`, `Live`, `fitInsets`.
- Produces: nothing for later tasks.

Behaviour:
- The lit items are `items.filter(i => step.item_ids.includes(i.id))` (the canvas's `items` prop, so removed ones drop out).
- When the step changes (key: `runId + index`), `setView(fitView(lit.map(itemBounds), size, insets))` with `insets = { ...fitInsets(size.width), bottom: 240 }` so the card has room under them; no view change when nothing is lit.
- The layer gets the lit items' live screen bounds (wrap in `Live items={lit}` per item, as the credit captions do, so moving items keep their holes).
- While a replay is on, the item toolbar, credit captions and hover tips are not drawn (they would sit on the dim).

- [ ] **Step 1: Write the failing tests**

```ts
it('fits the view to all lit items', () => {
  // three items far apart; startSpotlight with a step naming all three
  // the canvas view (read through the handle's center() or the stage transform) contains all three bounds
})

it('draws no item toolbar during a replay', () => {
  // one selected item; startSpotlight → the item toolbar is gone; closeSpotlight → back
})
```

- [ ] **Step 2: Run** the canvas test file — expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` (whole frontend suite) — expect PASS.
- [ ] **Step 5: Commit** `feat(spotlight): the canvas lights up and frames each step`

---

### Task 5: A link that opens the replay

**Files:**
- Modify: `frontend/src/shell/AgentCard.tsx`
- Test: `frontend/src/shell/AgentCard.test.tsx`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: the URL shape the landing page will use: `/boards/{board_id}?replay={run_id}`.

Behaviour: on mount, if `new URLSearchParams(window.location.search).get('replay')` names a run of this board, the card picks that run and, once its steps have loaded and it would show `Show me how`, starts the replay once. Afterwards the `replay` param is removed with `history.replaceState` (keeping the path), so a reload or a back navigation does not restart it. An unknown run id is ignored (the param is still removed).

- [ ] **Step 1: Write the failing tests**

```ts
it('opens the replay named in the link, once', () => {
  window.history.replaceState(null, '', '/boards/b1?replay=r1')
  renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
  expect(spotlightStore.get()?.runId).toBe('r1')
  expect(window.location.search).toBe('')
})

it('ignores a link to a run that is not on the board', () => {
  window.history.replaceState(null, '', '/boards/b1?replay=nope')
  renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
  expect(spotlightStore.get()).toBeNull()
  expect(window.location.search).toBe('')
})
```

- [ ] **Step 2: Run** `npx vitest run src/shell/AgentCard.test.tsx` — expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build` in `frontend/` — expect all green.
- [ ] **Step 5: Commit** `feat(spotlight): /boards/<id>?replay=<run> opens a replay`

---

### Task 6: Check it on the recorded boards

No code unless something is wrong. With the backend and `npm run dev` running, open each recorded board with its replay link and step through to the end, checking each card against `reports/demo/<slug>/steps.md` (the ★ lines that are `ok`):

- car `brd_01m6h989kz0tz8xjvjbp6zbz9x` (two runs: pick each in the Run select)
- UI `brd_01m6hcp4q8vrt11mnpw6jrmpb4`
- interior `brd_01m6j4rrnz1zzx6qax1rya3j27`
- fashion `brd_01m6j5n5eqdmxv33zhw03qesx5` (two runs)

Pass: every card's items are lit and in view; the board stays readable under the dim; Escape, arrows and Done behave; with `DEMO_MODE` locked the replay still plays. Write what you saw, one line per board, in the task report; fix anything that fails in the task that owns it.
