import type { Point } from '../api'

/** An `obstacle` (e.g. the selection toolbar) is never drawn: it sits at its home and only pushes. */
export type BodyKind = 'item' | 'kept' | 'hub' | 'petal' | 'callout' | 'badge' | 'obstacle'
export type Home = { kind: 'abs'; x: number; y: number } | { kind: 'rel'; to: string; dx: number; dy: number }

export interface BodySpec {
  id: string
  kind: BodyKind
  w: number
  h: number
  home: Home
  /** Where a new body starts (default: its home); e.g. a new hub starts at its anchor. */
  start?: Point
  /** ms after the sync that adds it before it appears (grow-in stagger). */
  delay?: number
  /** Collisions with this body id move only this one (a callout off its own item, never the item). */
  yieldTo?: string
}

export interface Body extends BodySpec {
  x: number
  y: number
  vx: number
  vy: number
  bornAt: number
  pulseAt: number
  pinned: boolean
  ph1: number
  ph2: number
  /** Size target: w/h ease toward it (spec w/h is the target). */
  tw: number
  th: number
}

export interface World {
  bodies: Map<string, Body>
}

export const FEEL = {
  drift: 3.2,
  driftW: [0.55, 0.42] as [number, number],
  damp: 0.86,
  dampReduced: 0.72,
  k: { item: 0.012, hub: 0.035, petal: 0.05, kept: 0.05, callout: 0.09, badge: 0.035, obstacle: 0 } as Record<BodyKind, number>,
  invMass: { item: 0.22, kept: 0.45, hub: 0.6, petal: 1, callout: 0.35, badge: 0.6, obstacle: 0 } as Record<BodyKind, number>,
  gap: 14,
  iterations: 3,
  push: 0.3,
  kick: 0.06,
  growMs: 450,
  hubLeadMs: 260,
  petalStaggerMs: 70,
  calloutStaggerMs: 45,
}

const GROW_REDUCED_MS = 250
/**
 * Passes of the hard resolve at most (it stops once nothing truly intersects): a row of bodies
 * squeezed together needs about one pass per body to pass the push along.
 */
const HARD_PASSES = 8
/** Separated bodies are left this far apart, so passing a push along does not re-touch them. */
const HARD_SLACK = 0.05
const SWELL_MS = 700
const SWELL_AMOUNT = 0.12
const SIZE_EASE = 0.14
const COLLIDE_MIN_SCALE = 0.25

export function createWorld(): World {
  return { bodies: new Map() }
}

export function syncWorld(w: World, specs: BodySpec[], now: number, rng: () => number = Math.random): void {
  const keep = new Set<string>()
  const added: Body[] = []
  for (const spec of specs) {
    keep.add(spec.id)
    const existing = w.bodies.get(spec.id)
    if (existing) {
      existing.kind = spec.kind
      existing.home = spec.home
      existing.start = spec.start
      existing.delay = spec.delay
      existing.yieldTo = spec.yieldTo
      existing.tw = spec.w
      existing.th = spec.h
      continue
    }
    const body: Body = {
      id: spec.id,
      kind: spec.kind,
      w: spec.w,
      h: spec.h,
      home: spec.home,
      start: spec.start,
      delay: spec.delay,
      yieldTo: spec.yieldTo,
      tw: spec.w,
      th: spec.h,
      x: 0,
      y: 0,
      vx: 0,
      vy: 0,
      bornAt: now,
      pulseAt: -Infinity,
      pinned: false,
      ph1: rng() * Math.PI * 2,
      ph2: rng() * Math.PI * 2,
    }
    w.bodies.set(spec.id, body)
    added.push(body)
  }
  for (const id of [...w.bodies.keys()]) if (!keep.has(id)) w.bodies.delete(id)

  // Second pass so a child listed before its new parent still starts beside it.
  const pending = new Set(added)
  const place = (b: Body): void => {
    pending.delete(b)
    if (b.home.kind === 'rel') {
      const parent = w.bodies.get(b.home.to)
      if (parent && pending.has(parent)) place(parent)
    }
    const p = b.start ?? homeOf(w, b)
    b.x = p.x
    b.y = p.y
  }
  for (const b of added) if (pending.has(b)) place(b)
}

export function homeOf(w: World, b: Body): Point {
  const h = b.home
  if (h.kind === 'abs') return { x: h.x, y: h.y }
  const parent = w.bodies.get(h.to)
  if (!parent) return { x: b.x, y: b.y }
  return { x: parent.x + h.dx, y: parent.y + h.dy }
}

const easeOutBack = (t: number): number => {
  const c1 = 1.70158
  const c3 = c1 + 1
  const u = Math.min(1, Math.max(0, t))
  return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2)
}

export function growScale(b: Body, now: number, reduced: boolean): number {
  const since = now - (b.bornAt + (b.delay ?? 0))
  if (since < 0) return 0
  const s = reduced ? Math.min(1, since / GROW_REDUCED_MS) : easeOutBack(since / FEEL.growMs)
  const sincePulse = now - b.pulseAt
  const swell = sincePulse < SWELL_MS ? 1 + SWELL_AMOUNT * Math.sin((Math.PI * sincePulse) / SWELL_MS) : 1
  return s * swell
}

export function stepWorld(w: World, dtFrames: number, now: number, opts: { reduced: boolean; awake?: (b: Body) => boolean }): void {
  const { reduced } = opts
  const awake = opts.awake ?? (() => true)
  const dt = Math.min(3, Math.max(0, dtFrames))
  const drift = reduced ? 0 : FEEL.drift
  const damp = reduced ? FEEL.dampReduced : FEEL.damp
  const t = now / 1000
  const bodies = [...w.bodies.values()]
  const ease = 1 - Math.pow(1 - SIZE_EASE, dt)
  for (const b of bodies) {
    b.w = reduced ? b.tw : b.w + (b.tw - b.w) * ease
    b.h = reduced ? b.th : b.h + (b.th - b.h) * ease
  }

  // Homes resolve against the parent's position before anyone moves this frame.
  const homes = bodies.map((b) => homeOf(w, b))
  bodies.forEach((b, i) => {
    const h = homes[i]
    if (b.kind === 'obstacle') {
      // no spring, no drift: exactly at its home
      b.x = h.x
      b.y = h.y
      b.vx = 0
      b.vy = 0
      return
    }
    if (b.pinned || !awake(b) || now < b.bornAt + (b.delay ?? 0)) return
    const tx = h.x + Math.sin(t * FEEL.driftW[0] + b.ph1) * drift
    const ty = h.y + Math.cos(t * FEEL.driftW[1] + b.ph2) * drift
    const k = FEEL.k[b.kind]
    b.vx = (b.vx + (tx - b.x) * k) * damp
    b.vy = (b.vy + (ty - b.y) * k) * damp
    b.x += b.vx * dt
    b.y += b.vy * dt
  })

  // Sleeping bodies neither move nor collide.
  const live = bodies.filter((b) => awake(b) && growScale(b, now, reduced) >= COLLIDE_MIN_SCALE)
  for (let it = 0; it < FEEL.iterations; it++) {
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const a = live[i]
        const c = live[j]
        const dx = c.x - a.x
        const dy = c.y - a.y
        const ox = (a.w + c.w) / 2 + FEEL.gap - Math.abs(dx)
        const oy = (a.h + c.h) / 2 + FEEL.gap - Math.abs(dy)
        if (ox <= 0 || oy <= 0) continue
        const ia = a.pinned || c.yieldTo === a.id ? 0 : FEEL.invMass[a.kind]
        const ic = c.pinned || a.yieldTo === c.id ? 0 : FEEL.invMass[c.kind]
        const sum = ia + ic
        if (!sum) continue
        let nx = 0
        let ny = 0
        let o: number
        if (ox < oy) {
          nx = Math.sign(dx) || 1
          o = ox
        } else {
          ny = Math.sign(dy) || 1
          o = oy
        }
        const m = (o * FEEL.push) / sum
        a.x -= nx * m * ia
        a.y -= ny * m * ia
        c.x += nx * m * ic
        c.y += ny * m * ic
        const kick = reduced ? 0 : (FEEL.kick * o) / sum
        a.vx -= nx * kick * ia
        a.vy -= ny * kick * ia
        c.vx += nx * kick * ic
        c.vy += ny * kick * ic
      }
    }
  }

  // The soft gap is the feel; true overlap is forbidden: what still intersects is moved apart by the
  // whole overlap (split by inverse mass, a pinned body or an obstacle takes none), with no kick.
  for (let pass = 0, moved = true; pass < HARD_PASSES && moved; pass++) {
    moved = false
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const a = live[i]
        const c = live[j]
        const dx = c.x - a.x
        const dy = c.y - a.y
        const ox = (a.w + c.w) / 2 - Math.abs(dx)
        const oy = (a.h + c.h) / 2 - Math.abs(dy)
        if (ox <= 0 || oy <= 0) continue
        const ia = a.pinned || c.yieldTo === a.id ? 0 : FEEL.invMass[a.kind]
        const ic = c.pinned || a.yieldTo === c.id ? 0 : FEEL.invMass[c.kind]
        const sum = ia + ic
        if (!sum) continue
        moved = true
        const alongX = ox < oy
        const n = alongX ? Math.sign(dx) || 1 : Math.sign(dy) || 1
        const o = (alongX ? ox : oy) + HARD_SLACK
        if (alongX) {
          a.x -= (n * o * ia) / sum
          c.x += (n * o * ic) / sum
        } else {
          a.y -= (n * o * ia) / sum
          c.y += (n * o * ic) / sum
        }
      }
    }
  }
}
