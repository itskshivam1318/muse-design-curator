/** Deterministic free-space layout for item callouts and exploration flowers (spec §6.3). Board items never move. */
import type { Point } from '../api'
import { rectsIntersect, unionBounds, type Bounds } from '../canvas/geometry'

export const CALLOUT_W = 176
export const CALLOUT_H = 56
export const HUB_W = 150
export const HUB_H = 48
export const PETAL = 88
export const PETAL_KEPT = 104
export const RING = 175
export const PETAL_GAP = 12
/** Distance from the source point to the hub centre along the flower's direction. */
export const HUB_DISTANCE = 120
/** Half-width of the petal arc (±115°). */
export const ARC_HALF = (115 * Math.PI) / 180
export const OUTWARD_STEP = 40
export const MAX_OUTWARD_STEPS = 40
/** Direction offsets tried, in order, once the outward sweep along a direction fails. */
export const DIR_OFFSETS = [0, 1, -1, 2, -2].map((k) => (k * Math.PI) / 6)

export interface FlowerInput {
  id: string
  from: Point
  dir: number
  petals: number
  kept: number[]
}

export interface FlowerLayout {
  hub: Bounds
  petals: Bounds[]
  /** Source -> hub, then hub -> each petal centre. */
  lines: [Point, Point][]
  bounds: Bounds
}

const centered = (c: Point, w: number, h: number): Bounds => ({ x: c.x - w / 2, y: c.y - h / 2, width: w, height: h })
const inflate = (b: Bounds, d: number): Bounds => ({ x: b.x - d, y: b.y - d, width: b.width + 2 * d, height: b.height + 2 * d })

/** First obstacle that `r` overlaps (stable order), or undefined. */
const firstHit = (r: Bounds, obstacles: Bounds[]) => obstacles.find((o) => rectsIntersect(r, o))

export function calloutSlots(
  item: Bounds,
  parts: { key: string; anchor: Point }[],
  obstacles: Bounds[],
): Map<string, Bounds> {
  type Side = 'left' | 'right' | 'below'
  const side = (a: Point): Side =>
    a.x < item.x + item.width / 3 ? 'left' : a.x > item.x + (item.width * 2) / 3 ? 'right' : 'below'
  const groups: Record<Side, { key: string; anchor: Point }[]> = { left: [], right: [], below: [] }
  for (const p of parts) groups[side(p.anchor)].push(p)

  const placed: Bounds[] = []
  const out = new Map<string, Bounds>()
  const taken = () => [...obstacles, ...placed]
  const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

  for (const s of ['left', 'right', 'below'] as Side[]) {
    const vertical = s !== 'below'
    const group = groups[s].sort((a, b) => (vertical ? a.anchor.y - b.anchor.y : a.anchor.x - b.anchor.x) || cmp(a.key, b.key))
    for (const p of group) {
      let r: Bounds = vertical
        ? {
            x: s === 'left' ? item.x - PETAL_GAP - CALLOUT_W : item.x + item.width + PETAL_GAP,
            y: p.anchor.y - CALLOUT_H / 2,
            width: CALLOUT_W,
            height: CALLOUT_H,
          }
        : { x: p.anchor.x - CALLOUT_W / 2, y: item.y + item.height + PETAL_GAP, width: CALLOUT_W, height: CALLOUT_H }
      for (let hit = firstHit(inflate(r, PETAL_GAP / 2), taken()); hit; hit = firstHit(inflate(r, PETAL_GAP / 2), taken())) {
        r = vertical ? { ...r, y: hit.y + hit.height + PETAL_GAP } : { ...r, x: hit.x + hit.width + PETAL_GAP }
      }
      placed.push(r)
      out.set(p.key, r)
    }
  }
  return out
}

function build(input: FlowerInput, dir: number, steps: number): FlowerLayout {
  const dist = HUB_DISTANCE + steps * OUTWARD_STEP
  const hubC = { x: input.from.x + Math.cos(dir) * dist, y: input.from.y + Math.sin(dir) * dist }
  const hub = centered(hubC, HUB_W, HUB_H)
  const kept = new Set(input.kept)
  const petals: Bounds[] = []
  const lines: [Point, Point][] = [[input.from, hubC]]
  for (let i = 0; i < input.petals; i++) {
    const a = input.petals === 1 ? dir : dir - ARC_HALF + (i * 2 * ARC_HALF) / (input.petals - 1)
    const c = { x: hubC.x + Math.cos(a) * RING, y: hubC.y + Math.sin(a) * RING }
    const size = kept.has(i) ? PETAL_KEPT : PETAL
    petals.push(centered(c, size, size))
    lines.push([hubC, c])
  }
  return { hub, petals, lines, bounds: unionBounds([hub, ...petals])! }
}

export function placeFlower(input: FlowerInput, obstacles: Bounds[]): FlowerLayout {
  for (const off of DIR_OFFSETS) {
    for (let steps = 0; steps <= MAX_OUTWARD_STEPS; steps++) {
      const l = build(input, input.dir + off, steps)
      if (!firstHit(inflate(l.bounds, PETAL_GAP), obstacles)) return l
    }
  }
  // Capped trials failed: keep stepping outward along `dir` until clear. Obstacles are finite, so this terminates.
  for (let steps = MAX_OUTWARD_STEPS + 1; ; steps++) {
    const l = build(input, input.dir, steps)
    if (!firstHit(inflate(l.bounds, PETAL_GAP), obstacles)) return l
  }
}

/**
 * Places flowers in id order; each placed flower becomes an obstacle for the next.
 * Contract: callers must pass EVERY flower, collapsed ones included (collapsing only hides rendering), and ids must
 * sort by creation order (monotonic ULIDs), so closing or collapsing a flower never shifts the others.
 */
export function layoutFlowers(flowers: FlowerInput[], items: Bounds[], callouts: Bounds[]): Map<string, FlowerLayout> {
  const sorted = [...flowers].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  const obstacles = [...items, ...callouts]
  const out = new Map<string, FlowerLayout>()
  for (const f of sorted) {
    const l = placeFlower(f, obstacles)
    out.set(f.id, l)
    obstacles.push(l.bounds)
  }
  return out
}

/** Ids of flowers whose bounds or source-to-hub connector reach the viewport. */
export function visibleFlowers(layouts: Map<string, FlowerLayout>, viewport: Bounds): string[] {
  return [...layouts]
    .filter(([, l]) => rectsIntersect(unionBounds([l.bounds, { ...l.lines[0][0], width: 0, height: 0 }])!, viewport))
    .map(([id]) => id)
}
