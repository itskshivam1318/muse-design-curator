/**
 * What a pointer release writes: the dragged bodies' new spots, read back as item positions, hub
 * offsets and dock changes, plus every docked take carried along (source → its hubs → their docked
 * takes → their hubs …). Pure; `commitRelease` (canvas/actions) applies and writes it as one undo step.
 */
import type { Exploration, Item, Point } from '../api'
import type { Move } from '../canvas/history'
import type { Home } from './physics'
import { dockedSize, undockedSize } from './ring'
import type { Scene } from './scene'

type Size = { w: number; h: number }
type Offset = { dx: number; dy: number }

export interface ReleasePlan {
  /** Item top-left moves (docked takes carried along included). */
  moves: Move[]
  hubs: { explorationId: string; from: Offset | null; to: Offset }[]
  dock: { optionId: string; itemId: string; undocked: boolean; size: Size; from: Size }[]
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

const topLeft = (c: Point, s: Size): Point => ({ x: Math.round(c.x - s.w / 2), y: Math.round(c.y - s.h / 2) })

export function planRelease(
  scene: Scene,
  items: readonly Item[],
  explorations: readonly Exploration[],
  released: ReadonlyMap<string, Point>,
  homeAfter: (id: string) => Point,
): ReleasePlan {
  const itemById = new Map(items.map((i) => [i.id, i]))
  const homes = new Map(scene.specs.map((s) => [s.id, s.home]))
  const moves: Move[] = []
  const hubs: ReleasePlan['hubs'] = []
  const dock: ReleasePlan['dock'] = []
  // each released body's centre once the dock rules have had their say (a take snaps to its slot)
  const final = new Map(released)
  const at = (id: string): Point => {
    const c = final.get(id)
    if (c) return c
    const h = homes.get(id)
    if (h?.kind !== 'rel') return homeAfter(id)
    const parent = at(h.to)
    return { x: parent.x + h.dx, y: parent.y + h.dy }
  }
  const slotAt = (h: Home): Point => (h.kind === 'abs' ? { x: h.x, y: h.y } : { x: at(h.to).x + h.dx, y: at(h.to).y + h.dy })
  const move = (it: Item, to: Point) => {
    if (to.x !== it.x || to.y !== it.y) moves.push({ id: it.id, from: { x: it.x, y: it.y }, to })
  }

  // dragged items first: a kept take docks or undocks by how near its slot it lands
  for (const [id, c] of released) {
    const it = itemById.get(id)
    if (!it || id.startsWith(HUB)) continue
    const slot = scene.slots.get(id)
    if (!slot) {
      move(it, topLeft(c, it))
      continue
    }
    const target = slotAt(slot.home)
    const near = Math.hypot(c.x - target.x, c.y - target.y) <= slot.reach
    const stored = { w: it.w, h: it.h }
    if (scene.docked.has(id) && !near) {
      const size = undockedSize(stored)
      dock.push({ optionId: slot.optionId, itemId: id, undocked: true, size, from: stored })
      move(it, topLeft(c, size))
    } else if (!scene.docked.has(id) && near) {
      const size = dockedSize(stored)
      dock.push({ optionId: slot.optionId, itemId: id, undocked: false, size, from: stored })
      final.set(id, target)
      move(it, topLeft(target, size))
    } else if (scene.docked.has(id)) {
      final.set(id, target)
      move(it, topLeft(target, stored))
    } else move(it, topLeft(c, stored))
  }

  // dragged hubs: their offset from where their source ends up
  const byId = new Map(explorations.map((e) => [e.id, e]))
  for (const [id, c] of released) {
    const e = id.startsWith(HUB) ? byId.get(id.slice(HUB.length)) : undefined
    if (!e) continue
    const source = at(e.item_id)
    const from = e.dx != null && e.dy != null ? { dx: e.dx, dy: e.dy } : null
    hubs.push({ explorationId: e.id, from, to: { dx: Math.round(c.x - source.x), dy: Math.round(c.y - source.y) } })
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

  return { moves, hubs, dock }
}
