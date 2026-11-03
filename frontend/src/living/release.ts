/**
 * What a pointer release writes: the dragged bodies' new spots, read back as item positions, hub
 * offsets and dock changes, plus every docked take carried along (source → its hubs → their docked
 * takes → their hubs …). Pure; `commitRelease` (canvas/actions) applies and writes it as one undo step.
 */
import type { Exploration, Item, Point } from '../api'
import type { Move } from '../canvas/history'
import type { Home } from './physics'
import { dockedSize, topLeft, undockedSize } from './ring'
import { keptSlot, type Scene } from './scene'
import type { LivingWorld } from './world'

type Size = { w: number; h: number }
type Offset = { dx: number; dy: number }

export interface ReleasePlan {
  /**
   * Item top-left moves (docked takes carried along included). `plain` marks a grabbed item that
   * neither was nor becomes a docked take: the only kind of write a locked demo makes.
   */
  moves: (Move & { plain?: boolean })[]
  hubs: { explorationId: string; from: Offset | null; to: Offset }[]
  dock: { optionId: string; itemId: string; undocked: boolean; size: Size; from: Size }[]
  /** Each released kept take's centre once the dock rules have had their say (its slot, or the drop). */
  settled: Map<string, Point>
}

const HUB = 'hub:'

/**
 * A body's home with the released centres applied: a rel home follows its parent's released centre
 * (or, not released, its parent's home); an abs home is the stored spot.
 */
export function homesAfter(scene: Scene, released: ReadonlyMap<string, Point>): (id: string) => Point {
  const homes = new Map(scene.specs.map((s) => [s.id, s.home]))
  const memo = new Map<string, Point>()
  const home = (id: string, seen: Set<string>): Point => {
    const got = memo.get(id)
    if (got) return got
    const h = homes.get(id)
    let p: Point
    if (!h) p = released.get(id) ?? { x: 0, y: 0 }
    else if (h.kind === 'abs') p = { x: h.x, y: h.y }
    else if (seen.has(h.to)) p = { x: 0, y: 0 } // a cycle: never built by the scene
    else {
      const parent = released.get(h.to) ?? home(h.to, new Set(seen).add(id))
      p = { x: parent.x + h.dx, y: parent.y + h.dy }
    }
    memo.set(id, p)
    return p
  }
  return (id) => home(id, new Set([id]))
}


export function planRelease(
  scene: Scene,
  items: readonly Item[],
  explorations: readonly Exploration[],
  released: ReadonlyMap<string, Point>,
  homeAfter: (id: string) => Point,
): ReleasePlan {
  const itemById = new Map(items.map((i) => [i.id, i]))
  const flowerByHub = new Map(scene.flowers.map((f) => [f.hubId, f]))
  const homes = new Map(scene.specs.map((s) => [s.id, s.home]))
  const moves: ReleasePlan['moves'] = []
  const hubs: ReleasePlan['hubs'] = []
  const dock: ReleasePlan['dock'] = []
  const settled = new Map<string, Point>()
  // released centres, then the dock rules' say (a take snaps to its slot)
  const final = new Map(released)
  // hubs given a new offset: their ring opens along it, so their docked takes' slots turn
  const turned = new Map<string, Point>()
  const slotHome = (id: string): Home | undefined => {
    const s = scene.slots.get(id)
    if (!s) return undefined
    const off = turned.get(s.hubId)
    const f = flowerByHub.get(s.hubId)
    if (!off || !f) return s.home
    const d = keptSlot(f, s.index, off)
    return { kind: 'rel', to: s.hubId, dx: d.x, dy: d.y }
  }
  const resolve = (h: Home | undefined, id: string): Point => {
    if (h?.kind !== 'rel') return homeAfter(id)
    const parent = at(h.to)
    return { x: parent.x + h.dx, y: parent.y + h.dy }
  }
  const at = (id: string): Point => final.get(id) ?? resolve(scene.docked.has(id) ? slotHome(id) : homes.get(id), id)
  const move = (it: Item, to: Point, plain = false) => {
    if (to.x === it.x && to.y === it.y) return
    moves.push({ id: it.id, from: { x: it.x, y: it.y }, to, ...(plain ? { plain } : {}) })
  }

  // dragged hubs (a hub is dragged on its own): their offset from their source
  const byId = new Map(explorations.map((e) => [e.id, e]))
  for (const [id, c] of released) {
    const e = id.startsWith(HUB) ? byId.get(id.slice(HUB.length)) : undefined
    if (!e) continue
    const source = at(e.item_id)
    const from = e.dx != null && e.dy != null ? { dx: e.dx, dy: e.dy } : null
    const to = { dx: Math.round(c.x - source.x), dy: Math.round(c.y - source.y) }
    hubs.push({ explorationId: e.id, from, to })
    turned.set(id, { x: to.dx, y: to.dy })
  }

  // dragged items: a kept take docks or undocks by how near its slot it lands
  for (const [id, c] of released) {
    const it = itemById.get(id)
    if (!it || id.startsWith(HUB)) continue
    const slot = scene.slots.get(id)
    const stored = { w: it.w, h: it.h }
    if (!slot) {
      move(it, topLeft(c, stored), true)
      continue
    }
    const target = resolve(slotHome(id), id)
    const near = Math.hypot(c.x - target.x, c.y - target.y) <= slot.reach
    const wasDocked = scene.docked.has(id)
    if (wasDocked !== near) {
      // undocked (it was docked and left its ring) or docked (it came back near its slot)
      const size = near ? dockedSize(stored) : undockedSize(stored)
      dock.push({ optionId: slot.optionId, itemId: id, undocked: !near, size, from: stored })
      const centre = near ? target : c
      settled.set(id, centre)
      move(it, topLeft(centre, size))
    } else if (wasDocked) {
      settled.set(id, target)
      move(it, topLeft(target, stored))
    } else {
      settled.set(id, c)
      move(it, topLeft(c, stored), true)
    }
    final.set(id, settled.get(id)!)
  }

  // docked takes reachable from a released body follow to their new slot
  const reached = new Set(released.keys())
  for (let grew = true; grew; ) {
    grew = false
    const reach = (from: string, to: string) => {
      if (!reached.has(from) || reached.has(to)) return
      reached.add(to)
      grew = true
    }
    for (const f of scene.flowers) reach(f.sourceId, f.hubId)
    for (const [take, { hubId }] of scene.docked) reach(hubId, take)
  }
  for (const id of scene.docked.keys()) {
    const it = itemById.get(id)
    if (!it || released.has(id) || !reached.has(id)) continue
    move(it, topLeft(at(id), it))
  }

  return { moves, hubs, dock, settled }
}

/**
 * A dragged take is selected, so pinned: it would stay where it was dropped. Put each released kept
 * take at its settled centre at once (its slot when it docked or snapped back), moved or not.
 */
export function placeSettled(world: Pick<LivingWorld, 'place'>, plan: ReleasePlan): void {
  for (const [id, c] of plan.settled) world.place(id, c)
}
