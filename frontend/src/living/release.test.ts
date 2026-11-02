import { describe, expect, it, vi } from 'vitest'
import type { AnalysisView, Exploration, Item, Point } from '../api'
import { makeItem } from '../test/fixtures'
import { analysis, exp, item, opt } from '../test/explore'
import { homesAfter, placeSettled, planRelease } from './release'
import { petalRadius } from './ring'
import { buildScene, keptSlot } from './scene'

// item 'a' (200x150 at the origin, centre (100, 75)) has a flower e1 whose hub sits 300 to its right;
// its kept option o2's take t1 (168x105) is docked in that ring, and t1 has a flower e2 of its own
// with a docked take t2
const t1 = makeItem({ id: 't1', board_id: 'b1', x: 600, y: 0, w: 168, h: 105, origin: 'generated', explore_option_id: 'o2' })
const t2 = makeItem({ id: 't2', board_id: 'b1', x: 900, y: 0, w: 168, h: 105, origin: 'generated', explore_option_id: 'o4' })

function board(over: { o2?: Partial<Parameters<typeof opt>[1]>; t1?: Partial<Item>; e1?: Partial<Exploration>; collapsed?: boolean } = {}) {
  const items = [item, { ...t1, ...over.t1 }, t2]
  const explorations = [
    exp('e1', 'hand_style', [opt('o1'), opt('o2', { kept_item_id: 't1', status: 'kept', ...over.o2 })], 'a', { dx: 300, dy: 0, ...over.e1 }),
    exp('e2', 'mood', [opt('o3', { exploration_id: 'e2' }), opt('o4', { exploration_id: 'e2', kept_item_id: 't2', status: 'kept' })], 't1', { dx: 0, dy: 300 }),
  ]
  const scene = buildScene({
    items,
    explorations,
    analyses: new Map<string, AnalysisView | null>([['a', analysis], ['t1', null]]),
    labels: new Map(),
    collapsed: (id) => id === 'e1' && !!over.collapsed,
    selectedId: null,
  })
  const plan = (released: Map<string, Point>) => planRelease(scene, items, explorations, released, homesAfter(scene, released))
  // where a body's home is before anything moves
  const before = homesAfter(scene, new Map())
  return { scene, plan, before }
}

const topLeft = (c: Point, s: { w: number; h: number }) => ({ x: Math.round(c.x - s.w / 2), y: Math.round(c.y - s.h / 2) })
const plus = (p: Point, dx: number, dy: number) => ({ x: p.x + dx, y: p.y + dy })

describe('planRelease', () => {
  it('dragging a source moves its docked takes too', () => {
    const { plan, before } = board()
    const p = plan(new Map([['a', { x: 150, y: 125 }]]))
    expect(p.moves).toEqual([
      { id: 'a', from: { x: 0, y: 0 }, to: { x: 50, y: 50 }, plain: true },
      { id: 't1', from: { x: 600, y: 0 }, to: topLeft(plus(before('t1'), 50, 50), t1) },
      // transitively: t1's own flower's docked take follows
      { id: 't2', from: { x: 900, y: 0 }, to: topLeft(plus(before('t2'), 50, 50), t2) },
    ])
    expect(p.hubs).toEqual([])
    expect(p.dock).toEqual([])
  })

  it('dragging a hub records from/to offsets', () => {
    const { scene, plan, before } = board()
    const p = plan(new Map([['hub:e1', { x: 450, y: 175 }]]))
    expect(p.hubs).toEqual([{ explorationId: 'e1', from: { dx: 300, dy: 0 }, to: { dx: 350, dy: 100 } }])
    expect(p.moves.map((m) => m.id)).toEqual(['t1', 't2'])
    // the ring opens along the new offset: t1's slot turns with it
    const slot = plus({ x: 450, y: 175 }, 0, 0)
    const d = keptSlot(scene.flowers[0], 1, { x: 350, y: 100 })
    const t1At = { x: slot.x + d.x, y: slot.y + d.y }
    expect(p.moves[0]).toEqual({ id: 't1', from: { x: 600, y: 0 }, to: topLeft(t1At, t1) })
    // and t1's own flower follows it
    const t1Before = before('t1')
    expect(p.moves[1].to).toEqual(topLeft(plus(before('t2'), t1At.x - t1Before.x, t1At.y - t1Before.y), t2))
    expect(p.moves.every((m) => !m.plain)).toBe(true)
    expect(p.dock).toEqual([])
  })

  it('a hub swung round to the other side of its source turns its ring with it', () => {
    const { scene, plan } = board()
    const hub = { x: 100 - 300, y: 75 }
    const p = plan(new Map([['hub:e1', hub]]))
    expect(p.hubs[0].to).toEqual({ dx: -300, dy: 0 })
    const d = keptSlot(scene.flowers[0], 1, { x: -300, y: 0 })
    // the ring turned half round: every slot is mirrored through the hub
    const was = keptSlot(scene.flowers[0], 1, { x: 300, y: 0 })
    expect([d.x, d.y]).toEqual([expect.closeTo(-was.x), expect.closeTo(-was.y)])
    expect(p.moves[0].to).toEqual(topLeft({ x: hub.x + d.x, y: hub.y + d.y }, t1))
  })

  it('a hub in its automatic slot records a null from', () => {
    const { plan, before } = board({ e1: { dx: null, dy: null } })
    const hub = before('hub:e1')
    const p = plan(new Map([['hub:e1', plus(hub, 10, 0)]]))
    expect(p.hubs).toEqual([{ explorationId: 'e1', from: null, to: { dx: Math.round(hub.x - 100 + 10), dy: Math.round(hub.y - 75) } }])
  })

  it('dragging a docked take beyond one ring radius undocks it at full size', () => {
    const { plan, before } = board()
    const drop = plus(before('t1'), petalRadius(2) + 1, 0)
    const p = plan(new Map([['t1', drop]]))
    const size = { w: 300, h: 187.5 }
    expect(p.dock).toEqual([{ optionId: 'o2', itemId: 't1', undocked: true, size, from: { w: 168, h: 105 } }])
    expect(p.moves[0]).toEqual({ id: 't1', from: { x: 600, y: 0 }, to: topLeft(drop, size) })
    expect(p.settled.get('t1')).toEqual(drop)
    // its own flower comes along
    expect(p.moves[1].id).toBe('t2')
  })

  it('a docked take dropped inside its ring goes back to its slot', () => {
    const { plan, before } = board()
    const p = plan(new Map([['t1', plus(before('t1'), 40, 0)]]))
    expect(p.dock).toEqual([])
    expect(p.moves.find((m) => m.id === 't1')).toEqual({ id: 't1', from: { x: 600, y: 0 }, to: topLeft(before('t1'), t1) })
    expect(p.settled.get('t1')).toEqual(before('t1'))
  })

  it('a docked take already stored at its slot settles there with no move', () => {
    const first = board()
    const at = topLeft(first.before('t1'), t1)
    const { plan, before } = board({ t1: at })
    const p = plan(new Map([['t1', plus(before('t1'), 40, 0)]]))
    expect(p.moves.find((m) => m.id === 't1')).toBeUndefined()
    expect(p.settled).toEqual(new Map([['t1', before('t1')]]))
  })

  it("a collapsed flower's takes dock within its badge ring", () => {
    const { scene, plan, before } = board({ collapsed: true })
    expect(scene.slots.get('t1')!.reach).toBe(70)
    expect(plan(new Map([['t1', plus(before('t1'), 80, 0)]])).dock[0]).toMatchObject({ undocked: true })
  })

  it('dropping an undocked take near its slot docks it at docked size', () => {
    const { scene, plan } = board({ o2: { undocked: true }, t1: { x: 2000, y: 2000, w: 300, h: 187.5 } })
    const slot = homesAfter(scene, new Map())
    const hub = slot('hub:e1')
    const h = scene.slots.get('t1')!.home as { dx: number; dy: number }
    const at = { x: hub.x + h.dx, y: hub.y + h.dy }
    const p = plan(new Map([['t1', plus(at, 30, -20)]]))
    const size = { w: 168, h: 105 }
    expect(p.dock).toEqual([{ optionId: 'o2', itemId: 't1', undocked: false, size, from: { w: 300, h: 187.5 } }])
    expect(p.moves[0]).toEqual({ id: 't1', from: { x: 2000, y: 2000 }, to: topLeft(at, size) })
    expect(p.settled.get('t1')).toEqual(at)
  })

  it('an undocked take dropped far from its slot just moves', () => {
    const { plan } = board({ o2: { undocked: true }, t1: { x: 2000, y: 2000, w: 300, h: 187.5 } })
    const p = plan(new Map([['t1', { x: 2250, y: 2100 }]]))
    expect(p.dock).toEqual([])
    expect(p.moves[0]).toEqual({ id: 't1', from: { x: 2000, y: 2000 }, to: { x: 2100, y: 2006 }, plain: true })
  })
})

describe('placeSettled', () => {
  it('puts every released kept take at its settled centre, moved or not', () => {
    const place = vi.fn()
    placeSettled({ place }, { moves: [], hubs: [], dock: [], settled: new Map([['t1', { x: 5, y: 6 }]]) })
    expect(place).toHaveBeenCalledExactlyOnceWith('t1', { x: 5, y: 6 })
  })
})
