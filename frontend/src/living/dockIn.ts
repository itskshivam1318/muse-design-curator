/**
 * The one-time move of takes kept before kept takes docked in their ring: each docked take still at
 * its old full size goes to its slot at the docked size. Pure; the Canvas runs it once per board load.
 */
import type { Item, Point } from '../api'
import { dockedSize } from './ring'
import type { Scene } from './scene'

/** Each docked take not yet at the docked size (more than 1px off), with its spot and size in its slot. */
export function staleDocked(
  scene: Scene,
  items: readonly Item[],
  slotOf: (itemId: string) => Point,
): { id: string; x: number; y: number; w: number; h: number }[] {
  const byId = new Map(items.map((i) => [i.id, i]))
  return [...scene.docked.keys()].flatMap((id) => {
    const it = byId.get(id)
    if (!it) return []
    const size = dockedSize(it)
    if (Math.abs(it.w - size.w) <= 1) return []
    const c = slotOf(id)
    return [{ id, x: Math.round(c.x - size.w / 2), y: Math.round(c.y - size.h / 2), ...size }]
  })
}
