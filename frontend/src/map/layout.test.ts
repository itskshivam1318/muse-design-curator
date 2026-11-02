import { describe, expect, it } from 'vitest'
import type { Bounds } from '../canvas/geometry'
import { rectsIntersect } from '../canvas/geometry'
import {
  CALLOUT_H,
  CALLOUT_W,
  HUB_H,
  HUB_W,
  PETAL,
  PETAL_KEPT,
  RING,
  calloutSlots,
  clampCard,
  layoutFlowers,
  placeBeside,
  placeFlower,
  visibleFlowers,
  type FlowerInput,
  type FlowerLayout,
} from './layout'

const item = (x: number, y: number, w = 240, h = 180): Bounds => ({ x, y, width: w, height: h })
const parts = (l: FlowerLayout): Bounds[] => [l.hub, ...l.petals]
const flower = (id: string, x: number, y: number, dir = 0, kept: number[] = [], itemId = 'i'): FlowerInput => ({
  id,
  itemId,
  from: { x, y },
  dir,
  petals: 6,
  kept,
})

describe('constants', () => {
  it('match the spec', () => {
    expect([CALLOUT_W, HUB_W, HUB_H, PETAL, PETAL_KEPT, RING]).toEqual([176, 150, 48, 88, 104, 175])
  })
})

describe('calloutSlots', () => {
  const it0 = item(500, 300)
  it('sit on the anchor side', () => {
    const slots = calloutSlots(
      it0,
      [
        { key: 'l', anchor: { x: 520, y: 380 } },
        { key: 'r', anchor: { x: 730, y: 380 } },
        { key: 'b', anchor: { x: 620, y: 470 } },
      ],
      [],
    )
    const l = slots.get('l')!
    expect(l.x + l.width).toBeLessThanOrEqual(it0.x)
    expect(slots.get('r')!.x).toBeGreaterThanOrEqual(it0.x + it0.width)
    expect(slots.get('b')!.y).toBeGreaterThanOrEqual(it0.y + it0.height)
  })

  it('stacks without overlap and avoids obstacles', () => {
    const obstacle = item(300, 330, 190, 60)
    const slots = calloutSlots(
      it0,
      ['a', 'b', 'c'].map((key) => ({ key, anchor: { x: 510, y: 350 } })),
      [obstacle],
    )
    const all = [...slots.values()]
    expect(all).toHaveLength(3)
    all.forEach((s, i) => {
      expect(s.width).toBe(CALLOUT_W)
      expect(s.height).toBe(CALLOUT_H)
      expect(rectsIntersect(s, obstacle)).toBe(false)
      all.slice(i + 1).forEach((o) => expect(rectsIntersect(s, o)).toBe(false))
    })
  })

  it('takes a card height per part, so tall cards on one side never overlap', () => {
    const slots = calloutSlots(
      it0,
      [
        { key: 'a', anchor: { x: 510, y: 320 }, height: 160 },
        { key: 'b', anchor: { x: 510, y: 330 } },
      ],
      [],
    )
    const a = slots.get('a')!
    const b = slots.get('b')!
    expect(a.height).toBe(160)
    expect(b.height).toBe(CALLOUT_H)
    expect(rectsIntersect(a, b)).toBe(false)
  })
})

describe('placeFlower', () => {
  it('lays six petals 46 degrees apart at RING and sizes kept petals larger', () => {
    const l = placeFlower({ id: 'a', itemId: 'i', from: { x: 0, y: 0 }, dir: 0, petals: 6, kept: [2] }, [])
    expect(l.petals).toHaveLength(6)
    expect(l.petals[2].width).toBe(PETAL_KEPT)
    expect(l.petals[0].width).toBe(PETAL)
    const hubC = { x: l.hub.x + l.hub.width / 2, y: l.hub.y + l.hub.height / 2 }
    const ang = l.petals.map((p) =>
      Math.atan2(p.y + p.height / 2 - hubC.y, p.x + p.width / 2 - hubC.x),
    )
    expect((ang[1] - ang[0]) * (180 / Math.PI)).toBeCloseTo(46, 5)
    const c = l.petals[0]
    expect(Math.hypot(c.x + c.width / 2 - hubC.x, c.y + c.height / 2 - hubC.y)).toBeCloseTo(RING, 5)
  })
})

describe('layoutFlowers', () => {
  const items = [item(0, 0), item(600, 0), item(300, 500)]
  const callouts = new Map([['i', [{ x: 250, y: 20, width: CALLOUT_W, height: CALLOUT_H }]]])
  const flowers = [
    flower('1', 120, 90),
    flower('2', 720, 90, Math.PI),
    flower('3', 420, 590, -Math.PI / 2, [1, 4]),
    flower('4', 120, 90, 0),
  ]

  it('petals never overlap items, callouts or other flowers', () => {
    const out = layoutFlowers(flowers, items, callouts)
    expect(out.size).toBe(4)
    const boxes = [...items, ...callouts.get('i')!]
    const ls = [...out.values()]
    ls.forEach((l, i) => {
      for (const p of parts(l)) {
        boxes.forEach((b) => expect(rectsIntersect(p, b)).toBe(false))
        ls.slice(i + 1).forEach((o) => parts(o).forEach((q) => expect(rectsIntersect(p, q)).toBe(false)))
      }
    })
  })

  it('opening a second flower does not move the first', () => {
    const a = layoutFlowers([flowers[0]], items, callouts).get('1')
    const both = layoutFlowers([flowers[1], flowers[0]], items, callouts).get('1')
    expect(both).toEqual(a)
  })

  it("a flower on another item, whose callouts overlap an existing flower, never moves it", () => {
    const a = layoutFlowers([flower('1', 120, 90)], items, callouts).get('1')!
    // item j's callouts land right on top of flower 1
    const onA = new Map([...callouts, ['j', [a.hub, a.petals[0]]]])
    const both = layoutFlowers([flower('1', 120, 90), flower('2', 720, 90, Math.PI, [], 'j')], items, onA)
    expect(both.get('1')).toEqual(a)
    // the later flower does keep clear of them
    parts(both.get('2')!).forEach((p) => onA.get('j')!.forEach((c) => expect(rectsIntersect(p, c)).toBe(false)))
  })

  it('boxed-in item pushes the flower outward', () => {
    const src = item(0, 0, 200, 150)
    const ring: Bounds[] = []
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2
      ring.push(item(100 + Math.cos(a) * 320 - 100, 75 + Math.sin(a) * 260 - 75, 200, 150))
    }
    const all = [src, ...ring]
    const snapshot = JSON.stringify(all)
    const l = layoutFlowers([flower('x', 100, 75)], all, new Map()).get('x')!
    expect(JSON.stringify(all)).toBe(snapshot)
    all.forEach((b) => expect(rectsIntersect(l.bounds, b)).toBe(false))
  })

  it('is deterministic', () => {
    expect(layoutFlowers(flowers, items, callouts)).toEqual(layoutFlowers(flowers, items, callouts))
  })

  it('is independent of input array order', () => {
    const shuffled = [flowers[2], flowers[0], flowers[3], flowers[1]]
    expect(layoutFlowers(shuffled, items, callouts)).toEqual(layoutFlowers(flowers, items, callouts))
  })

  it('keeps stepping outward past the capped trials until clear', () => {
    const wall = item(-5000, -5000, 10000, 10000)
    const l = layoutFlowers([flower('w', 0, 0)], [wall], new Map()).get('w')!
    expect(rectsIntersect(l.bounds, wall)).toBe(false)
  })

  it('places any number of flowers', () => {
    const many = Array.from({ length: 12 }, (_, i) => flower(String(i).padStart(2, '0'), 120, 90, i))
    const out = layoutFlowers(many, items, callouts)
    expect(out.size).toBe(12)
    const ls = [...out.values()]
    ls.forEach((l, i) => ls.slice(i + 1).forEach((o) => expect(rectsIntersect(l.bounds, o.bounds)).toBe(false)))
  })

  it('culls flowers outside the viewport', () => {
    const out = layoutFlowers([flower('near', 0, 0), flower('far', 5000, 5000)], [], new Map())
    expect(visibleFlowers(out, { x: -500, y: -500, width: 1000, height: 1000 })).toEqual(['near'])
  })

  it('counts the source connector as visible', () => {
    const far: Bounds = { x: 1000, y: 0, width: 100, height: 100 }
    const out = new Map<string, FlowerLayout>([
      ['c', { hub: far, petals: [], lines: [[{ x: 0, y: 0 }, { x: 1000, y: 50 }]], bounds: far }],
    ])
    const vp = { x: -50, y: -50, width: 80, height: 80 }
    expect(rectsIntersect(far, vp)).toBe(false)
    expect(visibleFlowers(out, vp)).toEqual(['c'])
  })
})

describe('placeBeside', () => {
  it('puts the box just outside the anchor along dir when the way is clear', () => {
    const petal = { x: 0, y: 0, width: 88, height: 88 }
    const b = placeBeside(petal, 0, { width: 200, height: 150 }, [petal])
    expect(b.x).toBeGreaterThan(petal.x + petal.width)
    expect(b.y + b.height / 2).toBeCloseTo(44)
  })

  it('steps around obstacles and never overlaps one', () => {
    const petal = { x: 0, y: 0, width: 88, height: 88 }
    const wall = { x: 100, y: -400, width: 300, height: 900 }
    const b = placeBeside(petal, 0, { width: 200, height: 150 }, [petal, wall])
    expect(rectsIntersect(b, wall)).toBe(false)
    expect(rectsIntersect(b, petal)).toBe(false)
    // deterministic
    expect(placeBeside(petal, 0, { width: 200, height: 150 }, [petal, wall])).toEqual(b)
  })
})

describe('clampCard', () => {
  const size = { width: 260, height: 300 }
  const area = { width: 1200, height: 800 }
  const agent = { x: 844, y: 584, width: 340, height: 200 } // bottom-right, 16px in

  it('leaves a card that fits where it is', () => {
    expect(clampCard({ x: 100, y: 100 }, size, area, agent)).toEqual({ x: 100, y: 100 })
  })

  it('pulls a card back inside the area, keeping the margin', () => {
    expect(clampCard({ x: 1100, y: -50 }, size, area, null)).toEqual({ x: 1200 - 8 - 260, y: 8 })
    expect(clampCard({ x: -40, y: 700 }, size, area, null)).toEqual({ x: 8, y: 800 - 8 - 300 })
  })

  it('moves a card off the agent card by the shorter way: left of it or above it', () => {
    // near its left edge: moving left is shorter
    expect(clampCard({ x: 700, y: 450 }, size, area, agent)).toEqual({ x: 844 - 8 - 260, y: 450 })
    // over its middle, near its top: moving up is shorter
    const tall = { width: 260, height: 100 }
    expect(clampCard({ x: 900, y: 560 }, tall, area, agent)).toEqual({ x: 900, y: 584 - 8 - 100 })
  })

  it('a card that cannot clear the agent card upward goes left of it', () => {
    const tall = { width: 260, height: 700 }
    const p = clampCard({ x: 900, y: 0 }, tall, area, agent)
    expect(p).toEqual({ x: 844 - 8 - 260, y: 8 })
  })
})
