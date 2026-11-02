/** Free-space placement for a kept result, and where an open card goes on screen. */
import type { Point } from '../api'
import { rectsIntersect, type Bounds } from '../canvas/geometry'

const GAP = 12
const OUTWARD_STEP = 40
const MAX_OUTWARD_STEPS = 40
/** Direction offsets tried, in order, once the outward sweep along a direction fails. */
const DIR_OFFSETS = [0, 1, -1, 2, -2].map((k) => (k * Math.PI) / 6)

const centered = (c: Point, w: number, h: number): Bounds => ({ x: c.x - w / 2, y: c.y - h / 2, width: w, height: h })
const inflate = (b: Bounds, d: number): Bounds => ({ x: b.x - d, y: b.y - d, width: b.width + 2 * d, height: b.height + 2 * d })

/**
 * A free `size` box beside `near` (e.g. a kept result next to its petal): its centre starts just clear
 * of `near`'s edge along `dir` and steps outward until, padded by GAP, it hits nothing; then the
 * DIR_OFFSETS directions; past the cap it keeps stepping along `dir`. Obstacles are finite, so this
 * terminates.
 */
export function placeBeside(near: Bounds, dir: number, size: { width: number; height: number }, obstacles: Bounds[]): Bounds {
  const c = { x: near.x + near.width / 2, y: near.y + near.height / 2 }
  const start = Math.max(near.width, near.height) / 2 + GAP + Math.max(size.width, size.height) / 2
  const make = (d: number, steps: number) => {
    const dist = start + steps * OUTWARD_STEP
    return centered({ x: c.x + Math.cos(d) * dist, y: c.y + Math.sin(d) * dist }, size.width, size.height)
  }
  const free = (b: Bounds) => !obstacles.some((o) => rectsIntersect(inflate(b, GAP), o))
  for (const off of DIR_OFFSETS) {
    for (let steps = 0; steps <= MAX_OUTWARD_STEPS; steps++) {
      const b = make(dir + off, steps)
      if (free(b)) return b
    }
  }
  for (let steps = MAX_OUTWARD_STEPS + 1; ; steps++) {
    const b = make(dir, steps)
    if (free(b)) return b
  }
}

/**
 * Where an open card of `size` goes (screen pixels, in the layer's own coordinates): at `at`, pulled inside
 * `area` (keeping `margin` from its edges), then off each of `avoid` in turn (the fixed agent card, the
 * selection toolbar) by the shorter of moving left of it or above it, or else below it.
 */
export function clampCard(
  at: Point,
  size: { width: number; height: number },
  area: { width: number; height: number },
  avoid: Bounds | readonly Bounds[] | null,
  margin = 8,
): Point {
  const within = (v: number, extent: number, room: number) => Math.max(margin, Math.min(v, room - margin - extent))
  let x = within(at.x, size.width, area.width)
  let y = within(at.y, size.height, area.height)
  const rects = avoid === null ? [] : Array.isArray(avoid) ? (avoid as readonly Bounds[]) : [avoid as Bounds]
  for (const r of rects) {
    if (!rectsIntersect({ x, y, width: size.width, height: size.height }, r)) continue
    const left = r.x - margin - size.width
    const up = r.y - margin - size.height
    const down = r.y + r.height + margin
    const canLeft = left >= margin
    const canUp = up >= margin
    if (canLeft && (!canUp || x - left <= y - up)) x = left
    else if (canUp) y = up
    else if (down + size.height <= area.height - margin) y = down
  }
  return { x, y }
}
