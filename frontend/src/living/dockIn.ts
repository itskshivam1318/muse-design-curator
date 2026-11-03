/**
 * The one-time move of takes kept before kept takes docked in their ring: each docked take still at
 * its old full size goes to its slot at the docked size. The Canvas runs it once per board load.
 */
import type { Item, Point } from '../api'
import { dockedSize, topLeft } from './ring'
import { dockedCentre, type FlowerModel, type Scene } from './scene'
import type { LivingWorld } from './world'

/** Where the take of the flower's option `index` docks now: round its hub and source where they are (null while either has no body). */
export function liveSlotCentre(world: Pick<LivingWorld, 'body'>, model: FlowerModel, index: number): Point | null {
  const hub = world.body(model.hubId)
  const source = world.body(model.sourceId)
  return hub && source ? dockedCentre(model, index, hub, source) : null
}

/** The top-left a take of `size` docks at in that slot now (null while the flower has no bodies). */
export function liveDockedAt(world: Pick<LivingWorld, 'body'>, model: FlowerModel, index: number, size: { w: number; h: number }): Point | null {
  const c = liveSlotCentre(world, model, index)
  return c && topLeft(c, size)
}

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
    return [{ id, ...topLeft(slotOf(id), size), ...size }]
  })
}
