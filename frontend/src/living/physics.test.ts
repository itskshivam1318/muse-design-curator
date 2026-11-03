import { describe, expect, it } from 'vitest'
import { FEEL, createWorld, growScale, homeOf, stepWorld, syncWorld, type BodySpec, type World } from './physics'

const item = (id: string, x: number, y: number, extra: Partial<BodySpec> = {}): BodySpec => ({
  id, kind: 'item', w: 100, h: 80, home: { kind: 'abs', x, y }, ...extra,
})

function run(w: World, steps: number, reduced: boolean, t0 = 1000): number {
  let now = t0
  for (let i = 0; i < steps; i++) {
    now += 16.67
    stepWorld(w, 1, now, { reduced })
  }
  return now
}

// The home spring and the soft positional push settle a few px inside the full gap.
const SOFT = 3 // doubled for a petal, whose home spring (0.05) pulls harder

describe('physics', () => {
  it('a lone body springs to its abs home', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { start: { x: 200, y: 0 } })], 0)
    run(w, 600, true)
    const a = w.bodies.get('a')!
    expect(Math.hypot(a.x, a.y)).toBeLessThan(0.5)
  })

  it('a rel home follows its parent', () => {
    const w = createWorld()
    syncWorld(w, [item('p', 0, 0), { id: 'c', kind: 'petal', w: 20, h: 20, home: { kind: 'rel', to: 'p', dx: 500, dy: 300 } }], 0)
    const now = run(w, 600, true)
    syncWorld(w, [item('p', 100, 50), w.bodies.get('c')!], now)
    run(w, 900, true, now)
    const c = w.bodies.get('c')!
    expect(c.x).toBeCloseTo(600, 0)
    expect(c.y).toBeCloseTo(350, 0)
  })

  // true overlap: the rects themselves intersecting (the soft gap aside)
  const trueOverlap = (a: { x: number; y: number; w: number; h: number }, c: { x: number; y: number; w: number; h: number }) =>
    Math.min((a.w + c.w) / 2 - Math.abs(a.x - c.x), (a.h + c.h) / 2 - Math.abs(a.y - c.y))

  it('no true overlap at rest: 8 petals squeezed by springs', () => {
    const w = createWorld()
    // eight petals whose homes sit only 60px apart around a pinned hub
    const petals: BodySpec[] = Array.from({ length: 8 }, (_, i) => {
      const a = -1 + (i * 2) / 7
      return { id: `p${i}`, kind: 'petal', w: 88, h: 88, home: { kind: 'rel', to: 'hub', dx: Math.cos(a) * 160, dy: Math.sin(a) * 160 } }
    })
    syncWorld(w, [{ id: 'hub', kind: 'hub', w: 150, h: 48, home: { kind: 'abs', x: 0, y: 0 } }, ...petals], 0)
    w.bodies.get('hub')!.pinned = true
    run(w, 900, true)
    const bodies = [...w.bodies.values()]
    for (let i = 0; i < bodies.length; i++)
      for (let j = i + 1; j < bodies.length; j++)
        expect(trueOverlap(bodies[i], bodies[j]), `${bodies[i].id} / ${bodies[j].id}`).toBeLessThanOrEqual(0.01)
  })

  it('a petal never rests inside a pinned item', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { w: 200, h: 150 }), { id: 'p', kind: 'petal', w: 88, h: 88, home: { kind: 'abs', x: 60, y: 40 } }], 0)
    w.bodies.get('a')!.pinned = true
    run(w, 900, true)
    expect(w.bodies.get('a')).toMatchObject({ x: 0, y: 0 })
    expect(trueOverlap(w.bodies.get('a')!, w.bodies.get('p')!)).toBeLessThanOrEqual(0.01)
  })

  it('an obstacle never moves and pushes a callout off it', () => {
    const w = createWorld()
    syncWorld(
      w,
      [
        item('a', 0, 0),
        { id: 'toolbar:a', kind: 'obstacle', w: 200, h: 40, home: { kind: 'rel', to: 'a', dx: 0, dy: -70 } },
        // a callout whose home sits right on the toolbar
        { id: 'callout:a:x', kind: 'callout', w: 120, h: 50, home: { kind: 'rel', to: 'a', dx: 0, dy: -75 }, yieldTo: 'a' },
      ],
      0,
    )
    w.bodies.get('a')!.pinned = true
    run(w, 600, true)
    const o = w.bodies.get('toolbar:a')!
    expect([o.x, o.y, o.vx, o.vy]).toEqual([0, -70, 0, 0])
    const c = w.bodies.get('callout:a:x')!
    const overlapX = (o.w + c.w) / 2 - Math.abs(c.x - o.x)
    const overlapY = (o.h + c.h) / 2 - Math.abs(c.y - o.y)
    expect(Math.min(overlapX, overlapY)).toBeLessThanOrEqual(0)
  })

  it('two overlapping bodies separate by at least the gap', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0), item('b', 0, 0)], 0)
    run(w, 600, true, 1000)
    const a = w.bodies.get('a')!
    const b = w.bodies.get('b')!
    const okX = Math.abs(a.x - b.x) >= 100 + FEEL.gap - SOFT
    const okY = Math.abs(a.y - b.y) >= 80 + FEEL.gap - SOFT
    expect(okX || okY).toBe(true)
  })

  it('a pinned body does not move and pushes a petal out', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0), { id: 'p', kind: 'petal', w: 40, h: 40, home: { kind: 'abs', x: 10, y: 0 } }], 0)
    w.bodies.get('a')!.pinned = true
    syncWorld(w, [item('a', 0, 0), w.bodies.get('p')!], 0)
    expect(w.bodies.get('a')!.pinned).toBe(true)
    run(w, 600, true, 1000)
    const a = w.bodies.get('a')!
    const p = w.bodies.get('p')!
    expect(a.x).toBe(0)
    expect(a.y).toBe(0)
    const okX = Math.abs(p.x - a.x) >= (100 + 40) / 2 + FEEL.gap - 2 * SOFT
    const okY = Math.abs(p.y - a.y) >= (80 + 40) / 2 + FEEL.gap - 2 * SOFT
    expect(okX || okY).toBe(true)
  })

  it('drift stays within FEEL.drift of home at rest', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 50, 50)], 0, () => 0.3)
    let now = run(w, 600, false)
    let max = 0
    for (let i = 0; i < 300; i++) {
      now += 16.67
      stepWorld(w, 1, now, { reduced: false })
      const a = w.bodies.get('a')!
      max = Math.max(max, Math.abs(a.x - 50), Math.abs(a.y - 50))
    }
    expect(max).toBeLessThanOrEqual(FEEL.drift + 0.5)
    expect(max).toBeGreaterThan(0.5)
  })

  it('reduced motion: at rest exactly at home', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 50, 50, { start: { x: 90, y: 10 } })], 0)
    run(w, 900, true)
    const a = w.bodies.get('a')!
    expect(Math.hypot(a.x - 50, a.y - 50)).toBeLessThanOrEqual(0.01)
  })

  it('a body not yet born neither moves others nor is drawn', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0), item('b', 0, 0, { delay: 5000 })], 1000)
    const b = w.bodies.get('b')!
    expect(growScale(b, 1000, false)).toBe(0)
    expect(growScale(b, 5999, false)).toBe(0)
    expect(growScale(b, 6000 + FEEL.growMs, false)).toBeGreaterThan(0.9)
    stepWorld(w, 1, 1100, { reduced: true })
    expect(w.bodies.get('a')!.x).toBe(0)
    expect(b.x).toBe(0)
    expect(b.vx).toBe(0)
  })

  it('growScale follows easeOutBack and the keep swell decays within 700 ms', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0)], 1000)
    const a = w.bodies.get('a')!
    expect(growScale(a, 1000, false)).toBeCloseTo(0, 5)
    // easeOutBack overshoots 1 on the way in, then settles exactly
    const mid = Array.from({ length: 45 }, (_, i) => growScale(a, 1000 + i * 10, false))
    expect(Math.max(...mid)).toBeGreaterThan(1.02)
    expect(growScale(a, 1000 + FEEL.growMs, false)).toBeCloseTo(1, 5)
    // reduced motion: linear, never past 1
    const lin = Array.from({ length: 40 }, (_, i) => growScale(a, 1000 + i * 10, true))
    expect(Math.max(...lin)).toBeLessThanOrEqual(1)
    expect(growScale(a, 1125, true)).toBeCloseTo(0.5, 5)
    // the keep swell: up at the middle of its 700 ms, gone by the end
    a.pulseAt = 5000
    expect(growScale(a, 5350, false)).toBeGreaterThan(1.1)
    expect(growScale(a, 5700, false)).toBe(1)
    expect(growScale(a, 6000, false)).toBe(1)
  })

  it('a body whose parent is gone keeps its place', () => {
    const w = createWorld()
    syncWorld(w, [item('p', 0, 0), { id: 'c', kind: 'petal', w: 20, h: 20, home: { kind: 'rel', to: 'p', dx: 100, dy: 0 } }], 0)
    const c = w.bodies.get('c')!
    expect(c.x).toBe(100)
    syncWorld(w, [c], 10)
    expect(homeOf(w, c)).toEqual({ x: 100, y: 0 })
    run(w, 100, true)
    expect(c.x).toBeCloseTo(100, 3)
  })

  it('a huge dt is clamped', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { start: { x: 300, y: -300 } }), item('b', 20, 20)], 0)
    stepWorld(w, 1000, 1000, { reduced: false })
    for (const b of w.bodies.values()) {
      expect(Number.isFinite(b.x) && Number.isFinite(b.y)).toBe(true)
      expect(Math.hypot(b.x - (b.home as { x: number }).x, b.y - (b.home as { y: number }).y)).toBeLessThan(500)
    }
  })

  it('sync keeps positions of bodies that stay and removes the rest', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { start: { x: 30, y: 40 } }), item('b', 500, 0)], 0)
    syncWorld(w, [item('a', 0, 0, { w: 150 })], 10)
    const a = w.bodies.get('a')!
    expect([a.x, a.y, a.tw]).toEqual([30, 40, 150])
    expect(w.bodies.has('b')).toBe(false)
    expect(a.bornAt).toBe(0)
  })

  it('a new child listed before its new parent starts at parent + offset', () => {
    const w = createWorld()
    const rel = (id: string, to: string, dx: number, dy: number): BodySpec => ({ id, kind: 'petal', w: 10, h: 10, home: { kind: 'rel', to, dx, dy } })
    syncWorld(w, [rel('petal', 'hub', 5, 6), rel('hub', 'it', 100, 200), item('it', 1000, 2000)], 0)
    expect(w.bodies.get('it')!.x).toBe(1000)
    expect([w.bodies.get('hub')!.x, w.bodies.get('hub')!.y]).toEqual([1100, 2200])
    expect([w.bodies.get('petal')!.x, w.bodies.get('petal')!.y]).toEqual([1105, 2206])
  })

  it('a resized body eases to its new size', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0)], 0)
    syncWorld(w, [item('a', 0, 0, { w: 200 })], 10)
    const a = w.bodies.get('a')!
    expect(a.w).toBe(100)
    stepWorld(w, 1, 1000, { reduced: false })
    expect(a.w).toBeGreaterThan(100)
    expect(a.w).toBeLessThan(200)
    run(w, 200, false)
    expect(a.w).toBeCloseTo(200, 1)
  })

  it('reduced motion snaps size', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0)], 0)
    syncWorld(w, [item('a', 0, 0, { w: 200, h: 10 })], 10)
    stepWorld(w, 1, 1000, { reduced: true })
    expect([w.bodies.get('a')!.w, w.bodies.get('a')!.h]).toEqual([200, 10])
  })

  it('a spec that drops yieldTo clears it', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { yieldTo: 'b' })], 0)
    syncWorld(w, [item('a', 0, 0)], 10)
    expect(w.bodies.get('a')!.yieldTo).toBeUndefined()
  })

  it('a body pushed onto the item it yields to is moved off it, and the item never moves', () => {
    const w = createWorld()
    syncWorld(
      w,
      [
        item('a', 0, 0),
        // a callout whose home overlaps its item, and a neighbour shoving it further in
        { id: 'callout:a:x', kind: 'callout', w: 120, h: 50, home: { kind: 'rel', to: 'a', dx: 0, dy: 50 }, yieldTo: 'a' },
        item('b', 0, 110),
      ],
      0,
    )
    run(w, 600, true)
    const a = w.bodies.get('a')!
    const c = w.bodies.get('callout:a:x')!
    expect([a.x, a.y]).toEqual([0, 0])
    const overlapX = (a.w + c.w) / 2 - Math.abs(c.x - a.x)
    const overlapY = (a.h + c.h) / 2 - Math.abs(c.y - a.y)
    expect(Math.min(overlapX, overlapY)).toBeLessThanOrEqual(0)
  })

  it('bodies the awake predicate rejects neither move nor collide', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { start: { x: 200, y: 0 } }), item('b', 0, 0, { start: { x: 10, y: 0 } })], 0)
    let now = 1000
    for (let i = 0; i < 20; i++) {
      now += 16.67
      stepWorld(w, 1, now, { reduced: true, awake: (b) => b.id === 'b' })
    }
    const a = w.bodies.get('a')!
    expect(a.x).toBe(200)
    expect(a.vx).toBe(0)
  })
})
