/** Pure canvas geometry: stage view transforms, zoom, fit and rectangle helpers. */
import type { Point } from '../api'

/** Stage position (screen px) and scale. A canvas point p appears on screen at p·scale + (x, y). */
export interface View {
  x: number
  y: number
  scale: number
}

export interface Bounds {
  x: number
  y: number
  width: number
  height: number
}

export const MIN_SCALE = 0.1
export const MAX_SCALE = 4

export const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))

/** Screen (container) point → canvas point: (pointer − stage position) / scale. */
export function toCanvasPoint(pointer: Point, view: View): Point {
  return { x: (pointer.x - view.x) / view.scale, y: (pointer.y - view.y) / view.scale }
}

export function toScreenPoint(p: Point, view: View): Point {
  return { x: p.x * view.scale + view.x, y: p.y * view.scale + view.y }
}

export function toScreenBounds(b: Bounds, view: View): Bounds {
  const p = toScreenPoint(b, view)
  return { x: p.x, y: p.y, width: b.width * view.scale, height: b.height * view.scale }
}

/** Zoom to `nextScale` (clamped) keeping the canvas point under `pointer` where it is. */
export function zoomAt(view: View, pointer: Point, nextScale: number): View {
  const scale = clampScale(nextScale)
  const anchor = toCanvasPoint(pointer, view)
  return { scale, x: pointer.x - anchor.x * scale, y: pointer.y - anchor.y * scale }
}

/** The same zoom, panned so `b` sits at the centre of a viewport of `size`. */
export function centeredView(view: View, b: Bounds, size: { width: number; height: number }): View {
  return { ...view, x: size.width / 2 - (b.x + b.width / 2) * view.scale, y: size.height / 2 - (b.y + b.height / 2) * view.scale }
}

/** Wheel delta → zoom factor: smooth for trackpad pinches (small deltas), ~1.35× per mouse-wheel notch. */
export function wheelZoomFactor(deltaY: number): number {
  return Math.exp(-Math.max(-30, Math.min(30, deltaY)) * 0.01)
}

export function unionBounds(all: Bounds[]): Bounds | null {
  if (all.length === 0) return null
  let x1 = Infinity
  let y1 = Infinity
  let x2 = -Infinity
  let y2 = -Infinity
  for (const b of all) {
    x1 = Math.min(x1, b.x)
    y1 = Math.min(y1, b.y)
    x2 = Math.max(x2, b.x + b.width)
    y2 = Math.max(y2, b.y + b.height)
  }
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 }
}

export interface Insets {
  top: number
  right: number
  bottom: number
  left: number
}

/** The view that shows all `items` inside the viewport, clear of the given insets (floating panels). */
export function fitView(
  items: Bounds[],
  viewport: { width: number; height: number },
  insets: Insets = { top: 80, right: 80, bottom: 80, left: 80 },
): View {
  const u = unionBounds(items)
  const w = Math.max(1, viewport.width - insets.left - insets.right)
  const h = Math.max(1, viewport.height - insets.top - insets.bottom)
  const cx = insets.left + w / 2
  const cy = insets.top + h / 2
  if (!u || u.width <= 0 || u.height <= 0) return { x: cx, y: cy, scale: 1 }
  const scale = clampScale(Math.min(w / u.width, h / u.height, 1))
  return {
    scale,
    x: cx - (u.x + u.width / 2) * scale,
    y: cy - (u.y + u.height / 2) * scale,
  }
}

export function normalizeRect(a: Point, b: Point): Bounds {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  }
}

export function rectsIntersect(a: Bounds, b: Bounds): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
}
