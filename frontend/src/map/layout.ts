/** Where an open card goes on screen. */
import type { Point } from '../api'
import { rectsIntersect, type Bounds } from '../canvas/geometry'

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
