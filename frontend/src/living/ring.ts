/** Ring geometry of the living board: where cards, hubs, petals and docked takes sit around their owner. */
import type { Point } from '../api'
import { FEEL } from './physics'

/** Card sizes (canvas units), mirrored by the .callout, .flower-hub and .petal CSS. */
export const CALLOUT_W = 176
export const HUB_W = 150
export const HUB_H = 48
export const PETAL = 88

/** A callout card clears its item by this much along each axis. */
export const CALLOUT_GAP = { x: 105, y: 46 }
/** A hub clears its source by this much along each axis (when it has no stored offset). */
export const HUB_GAP = { x: 210, y: 190 }
/** Petals spread ± this many radians around the hub's direction. */
export const PETAL_ARC = 2.35
/** A docked take sits this much further out than the petals. */
export const KEPT_EXTRA = 30
/** A take's width while docked in its ring, and once undocked onto the board. */
export const DOCKED_W = 168
export const UNDOCKED_W = 300

/**
 * One angle per anchor, spread evenly around the owner (2π/n apart), each as near as it can be to
 * where its anchor really is. Anchors are relative to the owner's centre; null is the whole item
 * (it prefers straight down, π/2). The owner is unused: offsets already carry its proportions.
 */
export function ringAngles(_owner: { w: number; h: number }, anchors: (Point | null)[]): number[] {
  const raw = anchors.map((p) => (p ? Math.atan2(p.y, p.x) : Math.PI / 2))
  const order = raw.map((a, i) => [a, i] as const).sort((p, q) => p[0] - q[0])
  const step = (2 * Math.PI) / anchors.length
  let best = { t0: 0, cost: Infinity }
  // try a start angle every 5°; the k-th anchor (by angle) takes slot t0 + k*step
  for (let s = 0; s < 72; s++) {
    const t0 = (s * Math.PI) / 36
    let cost = 0
    order.forEach(([a], k) => {
      const d = Math.atan2(Math.sin(t0 + k * step - a), Math.cos(t0 + k * step - a))
      cost += d * d
    })
    if (cost < best.cost) best = { t0, cost }
  }
  const out: number[] = []
  order.forEach(([, i], k) => {
    out[i] = best.t0 + k * step
  })
  return out
}

/** The offset from the owner's centre at `angle` on an ellipse clearing the owner by `gap`. */
export function ellipsePoint(owner: { w: number; h: number }, angle: number, gap: { x: number; y: number }): Point {
  return { x: Math.cos(angle) * (owner.w / 2 + gap.x), y: Math.sin(angle) * (owner.h / 2 + gap.y) }
}

/** The angles of `n` petals spread over ±PETAL_ARC around `dir` (one petal: straight along it). */
export function petalAngles(dir: number, n: number): number[] {
  if (n <= 1) return n === 1 ? [dir] : []
  return Array.from({ length: n }, (_, i) => dir - PETAL_ARC + (i * 2 * PETAL_ARC) / (n - 1))
}

/**
 * How far a hub's petals sit from it: wider rings for more petals, and never so tight that
 * neighbouring slots on the arc sit closer than a petal plus the gap (springs would squeeze them).
 */
export const petalRadius = (n: number) =>
  Math.max(135, n * 19, n > 1 ? (PETAL + FEEL.gap) / (2 * Math.sin(PETAL_ARC / (n - 1))) : 0)

/** The top-left of a box of `size` centred on `c`, rounded to whole canvas units (as positions are stored). */
export const topLeft = (c: Point, size: { w: number; h: number }): Point => ({
  x: Math.round(c.x - size.w / 2),
  y: Math.round(c.y - size.h / 2),
})

/** A take's size docked in its ring: DOCKED_W wide, same aspect. */
export function dockedSize(s: { w: number; h: number }): { w: number; h: number } {
  return { w: DOCKED_W, h: (s.h * DOCKED_W) / s.w }
}

/** A take's size once undocked onto the board: UNDOCKED_W wide, same aspect. */
export function undockedSize(s: { w: number; h: number }): { w: number; h: number } {
  return { w: UNDOCKED_W, h: (s.h * UNDOCKED_W) / s.w }
}
