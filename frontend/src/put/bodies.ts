/** "Put into" on the living board: the bodies its card and ghosts add, so nothing overlaps them. */
import type { Point } from '../api'
import type { BodySpec } from '../living/physics'
import type { Ghost } from './ghosts'

/** The card's size on screen (px), for its body on the board. */
export const PUT_CARD_W = 260
export const PUT_CARD_H = 170
export const PUT_CARD_ID = 'put-card'
export const ghostBodyId = (jobId: string) => `ghost:${jobId}`

/**
 * The living-board bodies "put into" adds (canvas units): the open card at `cardAt` (its centre), which
 * holds its place and only pushes, and each ghost, an item at the centre of where its result will land.
 */
export function putBodies(cardAt: Point | null, ghosts: readonly Ghost[], scale: number): BodySpec[] {
  const out: BodySpec[] = []
  if (cardAt) {
    const home = { kind: 'abs' as const, x: cardAt.x, y: cardAt.y }
    out.push({ id: PUT_CARD_ID, kind: 'obstacle', w: PUT_CARD_W / scale, h: PUT_CARD_H / scale, home })
  }
  for (const g of ghosts) {
    out.push({ id: ghostBodyId(g.jobId), kind: 'item', w: g.w, h: g.h, home: { kind: 'abs', x: g.x + g.w / 2, y: g.y + g.h / 2 } })
  }
  return out
}
