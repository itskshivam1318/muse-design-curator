import { describe, expect, it } from 'vitest'
import type { AnalysisView, Exploration, Item, Point } from '../api'
import { makeItem } from '../test/fixtures'
import { analysis, exp, item, opt } from '../test/explore'
import { homesAfter, planRelease } from './release'
import { petalRadius } from './ring'
import { buildScene } from './scene'

// item 'a' (200x150 at the origin, centre (100, 75)) has a flower e1 whose hub sits 300 to its right;
// its kept option o2's take t1 (168x105) is docked in that ring, and t1 has a flower e2 of its own
// with a docked take t2
const t1 = makeItem({ id: 't1', board_id: 'b1', x: 600, y: 0, w: 168, h: 105, origin: 'generated', explore_option_id: 'o2' })
const t2 = makeItem({ id: 't2', board_id: 'b1', x: 900, y: 0, w: 168, h: 105, origin: 'generated', explore_option_id: 'o4' })

function board(over: { o2?: Partial<Parameters<typeof opt>[1]>; t1?: Partial<Item>; e1?: Partial<Exploration> } = {}) {
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
    collapsed: () => false,
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
      { id: 'a', from: { x: 0, y: 0 }, to: { x: 50, y: 50 } },
      { id: 't1', from: { x: 600, y: 0 }, to: topLeft(plus(before('t1'), 50, 50), t1) },
      // transitively: t1's own flower's docked take follows
      { id: 't2', from: { x: 900, y: 0 }, to: topLeft(plus(before('t2'), 50, 50), t2) },
    ])
    expect(p.hubs).toEqual([])
    expect(p.dock).toEqual([])
  })

  it('dragging a hub records from/to offsets', () => {
    const { plan, before } = board()
    const p = plan(new Map([['hub:e1', { x: 450, y: 175 }]]))
    expect(p.hubs).toEqual([{ explorationId: 'e1', from: { dx: 300, dy: 0 }, to: { dx: 350, dy: 100 } }])
    expect(p.moves.map((m) => m.id)).toEqual(['t1', 't2'])
    expect(p.moves[0].to).toEqual(topLeft(plus(before('t1'), 50, 100), t1))
    expect(p.dock).toEqual([])
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
    // its own flower comes along
    expect(p.moves[1].id).toBe('t2')
  })

  it('a docked take dropped inside its ring goes back to its slot', () => {
    const { plan, before } = board()
    const p = plan(new Map([['t1', plus(before('t1'), 40, 0)]]))
    expect(p.dock).toEqual([])
    expect(p.moves.find((m) => m.id === 't1')?.to ?? { x: 600, y: 0 }).toEqual(topLeft(before('t1'), t1))
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
  })

  it('an undocked take dropped far from its slot just moves', () => {
    const { plan } = board({ o2: { undocked: true }, t1: { x: 2000, y: 2000, w: 300, h: 187.5 } })
    const p = plan(new Map([['t1', { x: 2250, y: 2100 }]]))
    expect(p.dock).toEqual([])
    expect(p.moves[0]).toEqual({ id: 't1', from: { x: 2000, y: 2000 }, to: { x: 2100, y: 2006 } })
  })
})
