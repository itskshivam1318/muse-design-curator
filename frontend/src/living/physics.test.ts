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

  it('an obstacle never moves and pushes a callout off it', () => {
    const w = createWorld()
    syncWorld(
      w,
      [
        item('a', 0, 0),
        { id: 'toolbar:a', kind: 'obstacle', w: 200, h: 40, home: { kind: 'rel', to: 'a', dx: 0, dy: -70 } },
        // a callout whose home sits right on the toolbar
        { id: 'callout:a:x', kind: 'callout', w: 120, h: 50, home: { kind: 'rel', to: 'a', dx: 0, dy: -75 }, ignore: 'a' },
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

  it('a spec that drops ignore clears it', () => {
    const w = createWorld()
    syncWorld(w, [item('a', 0, 0, { ignore: 'b' })], 0)
    syncWorld(w, [item('a', 0, 0)], 10)
    expect(w.bodies.get('a')!.ignore).toBeUndefined()
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
