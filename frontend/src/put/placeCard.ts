/**
 * Where the Put card opens: at a corner of the drop point that sits inside the screen and clear of
 * what must stay visible (the agent card). Pure, in the layer's own pixel space.
 */
export interface Rect { left: number; top: number; right: number; bottom: number }

const MARGIN = 16

const overlaps = (a: Rect, b: Rect) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top

/** The card's top-left: right-below, left-below, right-above or left-above of `drop`, the first that fits; else clamped in. */
export function placeCard(
  drop: { x: number; y: number },
  card: { w: number; h: number },
  viewport: { w: number; h: number },
  avoid: readonly Rect[],
): { x: number; y: number } {
  const rect = (x: number, y: number): Rect => ({ left: x, top: y, right: x + card.w, bottom: y + card.h })
  const inside = (r: Rect) =>
    r.left >= MARGIN && r.top >= MARGIN && r.right <= viewport.w - MARGIN && r.bottom <= viewport.h - MARGIN
  const tries = [
    { x: drop.x, y: drop.y },
    { x: drop.x - card.w, y: drop.y },
    { x: drop.x, y: drop.y - card.h },
    { x: drop.x - card.w, y: drop.y - card.h },
  ]
  for (const t of tries) {
    const r = rect(t.x, t.y)
    if (inside(r) && !avoid.some((a) => overlaps(r, a))) return t
  }
  // none fits as is: slide each into the screen; failing that, stand beside or above what is avoided
  const clamp = (v: number, size: number, max: number) => Math.max(MARGIN, Math.min(v, max - size - MARGIN))
  const slide = (t: { x: number; y: number }) => ({ x: clamp(t.x, card.w, viewport.w), y: clamp(t.y, card.h, viewport.h) })
  const fits = (t: { x: number; y: number }) => !avoid.some((a) => overlaps(rect(t.x, t.y), a))
  const slid = tries.map(slide)
  const beside = avoid.flatMap((a) => [
    slide({ x: a.left - card.w - MARGIN, y: drop.y }),
    slide({ x: drop.x, y: a.top - card.h - MARGIN }),
  ])
  return [...slid, ...beside].find(fits) ?? slid[0]
}
