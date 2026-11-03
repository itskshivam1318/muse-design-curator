/** "Put into" on the living board: the bodies its card and ghosts add, so nothing overlaps them. */
import type { Point } from '../api'
import type { Bounds } from '../canvas/geometry'
import type { BodySpec } from '../living/physics'
import type { Ghost } from './ghosts'

/** The card's size on screen (px) until it is measured. */
export const PUT_CARD_W = 260
export const PUT_CARD_H = 170
export const PUT_CARD_ID = 'put-card'
export const ghostBodyId = (jobId: string) => `ghost:${jobId}`
/** The card's clearance from the pictures beside it (canvas units). */
const CARD_GAP = 16

/**
 * Where the card opens (its centre, canvas units): beside the target, on the side away from the source,
 * and beyond the source and its toolbar (`toolbar`: its size, centred just above the source) on that
 * side too. The source stays selected, so pinned, and its toolbar is an obstacle: the card would only be
 * pushed off them, so it starts clear of both.
 */
export function cardPlace(source: Bounds, target: Bounds, card: { w: number; h: number }, toolbar?: { w: number; h: number }): Point {
  const sc = source.x + source.width / 2
  const tc = target.x + target.width / 2
  const half = Math.max(source.width, toolbar?.w ?? 0) / 2 // the source's reach either side, its toolbar included
  const y = target.y + target.height / 2
  if (sc <= tc) return { x: Math.max(target.x + target.width, sc + half) + CARD_GAP + card.w / 2, y }
  return { x: Math.min(target.x, sc - half) - CARD_GAP - card.w / 2, y }
}

/**
 * The living-board bodies "put into" adds (canvas units): the open card at `cardAt` (its centre, its size as drawn), a
 * callout held there by its home that gives way to whatever it meets, pinned pictures and toolbars included (so a picture
 * dropped on it or a toolbar reaching it never overlaps it), and each ghost, an item at the centre of where its result
 * will land.
 */
export function putBodies(
  cardAt: Point | null,
  ghosts: readonly Ghost[],
  scale: number,
  /** The card as drawn (screen px); null until measured. */
  cardSize: { width: number; height: number } | null = null,
): BodySpec[] {
  const out: BodySpec[] = []
  if (cardAt) {
    const home = { kind: 'abs' as const, x: cardAt.x, y: cardAt.y }
    const w = (cardSize?.width || PUT_CARD_W) / scale
    const h = (cardSize?.height || PUT_CARD_H) / scale
    out.push({ id: PUT_CARD_ID, kind: 'callout', w, h, home })
  }
  for (const g of ghosts) {
    out.push({ id: ghostBodyId(g.jobId), kind: 'item', w: g.w, h: g.h, home: { kind: 'abs', x: g.x + g.w / 2, y: g.y + g.h / 2 } })
  }
  return out
}
