/** Where a part sits on its item: region boxes in canvas units, callout anchors, display tags. */
import type { PartView, Point, Region, RegionKind } from '../api'
import type { Bounds } from '../canvas/geometry'
import { NOTE_PAD } from '../canvas/noteSize'

/** A hovered region's tint (a mask's fill is this at REGION_ALPHA; outlines and passages are solid). */
export const REGION_COLOR = '#ffd166'
export const REGION_ALPHA = 0.35

/** The small tag on a part's callout. */
export const REGION_TAG: Record<RegionKind, string> = { mask: 'SAM mask', box: 'box', text_range: 'passage' }

/** A [x0, y0, x1, y1] box (fractions of the item) in the item's own coordinates. */
export function boxBounds(item: Bounds, box: readonly number[]): Bounds {
  const [x0, y0, x1, y1] = box
  return {
    x: item.x + x0 * item.width,
    y: item.y + y0 * item.height,
    width: (x1 - x0) * item.width,
    height: (y1 - y0) * item.height,
  }
}

/** Where a part's leader line ends: its region's centre; a passage at the note's edge beside its text. */
export function partAnchor(item: Bounds, part: PartView, text?: string | null): Point {
  const centre = { x: item.x + item.width / 2, y: item.y + item.height / 2 }
  const r = part.region
  if (part.region_kind === 'text_range') {
    if (!r || r.length !== 2 || !text) return centre
    const mid = Math.min(1, Math.max(0, (r[0] + r[1]) / 2 / text.length))
    return { x: item.x + item.width - NOTE_PAD, y: item.y + item.height * mid }
  }
  if (!r || r.length !== 4) return centre
  const b = boxBounds(item, r)
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
}

/**
 * What to draw for a hovered part: its region once known; until then the stored region (a box or a
 * passage is already exact) or, for a mask being found, a loading outline of its bbox. A mask that
 * could not be found falls back to an outline of its bbox (or of the whole item).
 */
export function regionOf(part: PartView | undefined, fetched: Region | undefined, pending: boolean): { region: Region; loading: boolean } | null {
  if (!part) return null
  if (fetched) return { region: fetched, loading: false }
  const r = part.region ?? undefined
  if (part.region_kind === 'box') return r ? { region: { kind: 'box', box: r }, loading: false } : null
  if (part.region_kind === 'text_range') return r ? { region: { kind: 'text_range', range: r }, loading: false } : null
  return { region: { kind: 'mask', box: r }, loading: pending }
}
