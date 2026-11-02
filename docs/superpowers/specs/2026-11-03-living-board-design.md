# Living board: fluid nodes, connected flowers, kept-in-ring — design

Date: 2026-11-03. Status: approved by the owner via a throwaway prototype ("the drift feels right, build it into the app").

Prototype (throwaway, behaviour reference only): `docs/superpowers/specs/2026-11-03-living-board-prototype/living-board.html` (open via any static server) — vanilla JS, ~400 lines. Its constants (drift ±3.2px at 0.55/0.42 rad/s, damping 0.86, home spring k 0.012 items / 0.035 hubs / 0.05 petals / 0.09 callouts, inverse masses 0.22 items / 0.45 kept / 0.6 hubs / 1 petals / 0.35 callouts, collide gap 14, 3 positional iterations at 0.3 with a small velocity kick, grow-in easeOutBack 450 ms, petals staggered 70 ms after a 260 ms hub lead) are the owner-approved feel; start from them.

## Intent

The board today is frozen: flowers are placed once by a deterministic free-space sweep, callouts line up in a
row under the image, flowers look cut off from their image unless it is selected, kept results jump out of
their ring to a separate spot, and nothing makes room when you move something. The owner wants the board to
feel **alive, like things floating on water**: every node drifts gently, nodes bump and push each other
instead of overlapping, new explorations grow in with motion, and exploration reads as one connected,
branching tree that you keep working on in place.

Success: on the "cars" board (screenshots of 2026-11-03), nothing overlaps, every flower is visibly joined to
the image it grew from at all times, a kept take sits in its ring and can be explored further from there, and
dragging anything makes the neighbours ease aside and drift back.

## Goals

1. **Add button on the board.** A floating **+** button next to the Select / Note / Nodes tool dock opens a
   popover with the existing `AddActions` (Upload image · Paste link · Extension). The Library panel keeps
   its copy. Disabled in locked demo mode exactly as `AddActions` is today.
2. **Callouts in a ring around the image.** Each part callout sits on the ray from the item's centre through
   its part anchor, just outside the item's bounds. Collisions slide callouts *around* the ring (angularly),
   not downward. Whole-item / anchorless callouts take the free angle nearest the bottom.
3. **Flowers always connected.** The stem is drawn whether or not the item is selected:
   - item not selected: a curved branch from the hub to the part's anchor on the image (whole-item
     dimensions: the nearest point on the image edge);
   - item selected: hub → callout → anchor, as now but curved.
   No dangling stems or stray root dots.
4. **Kept take stays in its ring.** Keeping a take turns that petal into the image, in the same ring slot,
   joined to the hub by its spoke. It is shown larger than an option card but smaller than a normal board
   image (builder picks the size; it must still read as a ring). It is a real board item: select it to see
   its callouts, open its dimensions, and a new flower grows **from the petal**. Exploration becomes a
   branching tree (car → Body color → kept green car → Front wheel → …), every branch visibly connected.
5. **Fluid physics for everything on the board.** Images, notes, links, flower hubs, petals (kept or not)
   and callouts are bodies in one continuous simulation:
   - **No overlaps**: bodies collide as rectangles (with a small gap) and push each other apart.
   - **Home springs**: every body is pulled toward its *home* (below). Pushed things float back slowly.
   - **Structure springs**: petals held at ring distance from their hub; hub held near its source by its
     stem; callouts held to their ring slot around the item.
   - **Drift**: at rest, each body bobs a few pixels at its own slow rhythm (calm, never busy).
   - **Dragging**: the dragged body follows the pointer exactly; it pushes neighbours, which ease aside and
     settle. Releasing sets that body's new home (for things that have a stored home).
   - **Lines are soft**: stems and spokes are curves that bend with the motion.
6. **Life on creation.** A new flower's hub grows out from its source along the stem, then its petals unfold
   around it one after another. Keep plays a small swell as the petal grows into the image. New items fade/scale
   in and the neighbours make room.
7. **Every flower is draggable by its hub**; its petals (and kept takes docked in it) come along.

## Homes and what is stored

Each body has a *home*, the spot it floats back to. **Only homes are stored — never drift or push offsets** —
so a reload or another viewer sees everything settled at home.

| Body | Home | Stored where |
|---|---|---|
| Board item (image, note, link) | where the user last put it | existing `board_items.x/y` (unchanged) |
| Flower hub | an **offset from its source** (item or kept take) — where the user last dragged the hub relative to that source; if never dragged, an auto-chosen offset. Moving the source carries its flowers along | new nullable `explorations.dx/dy` (migration 0009); null = auto |
| Petal (option card) | its slot on the hub's ring | not stored (derived from hub) |
| Kept take, docked | its ring slot (follows the hub) | the item's `x/y` is rewritten to the slot when it settles after the hub moves; "docked" state below |
| Kept take, pulled out | where the user dropped it | `board_items.x/y`; spoke stretches but stays drawn |
| Callout | its slot on the item's ring | not stored |

**Docked vs pulled out (builder's call how to store it):** a kept take is docked while it is in its ring;
dragging it beyond a threshold (≈ one ring radius from its slot) undocks it; dragging it back near its slot
re-docks it. The existing `explore_options.x/y` columns are unused by the frontend today and may be reused
for this, or a flag added — builder decides.

**Auto offsets for never-dragged hubs**: the flower opens along the same angle as its part's callout slot in the
ring around the source (so flowers radiate evenly around an image), at roughly the source's half-size + ~200px.
Physics resolves any crowding. Persisting the auto offset on first settle is acceptable.

## Non-goals

- No change to analysis, exploration generation, visualize or keep *semantics* on the backend beyond: the
  hub position columns, and keep placing the item at the ring slot.
- No multi-user live sync of motion; other viewers see homes via the existing SSE item/exploration updates.
- No new explore features (steer, more options) — only where things sit and how they move.
- Collapse-to-badge stays; a collapsed flower is one small body (the badge) in the simulation.

## Anti-goals (would be a failure even if it technically works)

- A busy, jittery or seasick board. Drift is a few px and slow; settling is damped, no endless oscillation.
- Things ever overlapping at rest, or a flower ever looking disconnected from its source.
- Positions changing in storage without the user moving something (except the one-time auto-home persist and
  docked kept takes following their hub).
- Dropping frames on a board the size of "cars" (~10 images, ~8 flowers, ~80 petals) on a laptop.
- Breaking pan/zoom, marquee select, undo of moves, Escape rules, or keyboard access to petals/callouts.

## Constraints

- Canvas is Konva (`react-konva`) for items; callouts, flowers and petal cards are HTML in canvas units over
  it (`map/Callouts.tsx`, `map/Flower.tsx`). The simulation must drive both from one source of positions.
- `prefers-reduced-motion`: drift, bounce and creation flourishes are off; things still move out of the way,
  gliding straight to rest.
- Locked demo mode (`DEMO_MODE`): viewers see the drift and can drag things locally for fun, but nothing is
  saved (no home writes); add button disabled.
- Undo (`canvas/history.ts`) covers user moves of items as now; hub moves should be undoable the same way.
- Off-screen bodies may sleep (be simulated coarsely or frozen) to stay cheap; anything near the viewport is
  live. Only flowers reaching the viewport mount today — keep that.
- Frontend tests (vitest) and e2e must stay green; the physics core should be pure and unit-testable
  (step function in, positions out), separate from React.

## Decided by the owner

- Images move (they are bodies too). Flowers are draggable by the hub.
- Kept take stays in its ring and is explored further from there (own callouts, own flowers from the petal).
- At rest: gentle drift, like floating on water.
- Something pushed aside floats back slowly to its home.
- Add button back on the board.
- Callouts around the image, not in a line.

## Builder-check answers

- **Existing kept takes (owner decision):** kept takes created before this ships are moved into their ring
  automatically, once, the first time the board loads with the new client (treated as docked). This is the one
  allowed storage change the user didn't make by hand. After that they behave like any docked take.
- **Docked size (my call):** a docked kept take's stored `w/h` is shrunk to the docked size (same aspect, ~168px
  wide) so it stays an ordinary Konva board item (selectable, callouts, nested flowers, drag). Undocking grows it
  back to a normal board size (~300px wide, its aspect) and writes `w/h`. Keep writes the docked size.
- **Collapse (my call):** collapsing a flower hides its option cards only; docked kept takes stay visible, clustered
  around the badge (their ring shrinks to fit the badge), and their own flowers stay as they are.
- **Callouts (my call):** callouts are collision bodies only while shown (as in the prototype); selecting an image
  nudges its neighbours aside. Auto hub offsets are measured from the source bounds, not the callout ring.
- **Undo and writes (my call):** dragging a source together with everything attached is one undo entry and one
  batched write on pointer release (item x/y, hub dx/dy, docked takes' x/y). Docked takes' x/y are written on
  release of whatever moved them — never continuously, never from drift.

## My calls (not discussed with the owner)

- **+** button placement beside the tool dock; reuses `AddActions` in a popover; Library keeps its copy.
- Reduced motion turns off drift/bounce/flourishes.
- Kept take docked size between petal and full image; undock threshold ≈ one ring radius.
- Physics engine: builder's choice between a small hand-rolled verlet/spring step and `d3-force` with a
  custom rectangle-collide force. Hand-rolled is preferred if it stays small, since the layout is rectangles.
- Flowers travel with their source when it is dragged (hub home is relative) — confirmed in the prototype.
- Callout ring: callouts spread *evenly* around the item, each slot assigned to minimise the angular distance to
  its part's real anchor (prototype `ringAngles`).
- The old contract in `map/layout.ts` ("board items never move; opening a flower never moves another") is
  retired; that file's free-space sweep survives only for picking initial homes.

## Left to the builder

- Exact spring constants, damping, drift amplitude/period (tune by eye on the "cars" board).
- Curve shapes for stems/spokes; animation timings.
- Whether callouts are full simulation bodies or positioned analytically around their (moving) item.
- How undocked state is stored (see above).
- Order of work. Suggested: (1) add button, (2) always-connected stems, (3) callout ring, (4) physics core +
  items/hubs/petals, (5) hub drag + migration, (6) kept-in-ring + nested flowers, (7) creation animations.
