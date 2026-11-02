import type { Point } from '../api'

export type BodyKind = 'item' | 'kept' | 'hub' | 'petal' | 'callout' | 'badge'
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
  /** Skip collisions with this body id (a callout with its own item). */
  ignore?: string
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
}

export interface World {
  bodies: Map<string, Body>
}

export const FEEL = {
  drift: 3.2,
  driftW: [0.55, 0.42] as [number, number],
  damp: 0.86,
  dampReduced: 0.72,
  k: { item: 0.012, hub: 0.035, petal: 0.05, kept: 0.05, callout: 0.09, badge: 0.035 } as Record<BodyKind, number>,
  invMass: { item: 0.22, kept: 0.45, hub: 0.6, petal: 1, callout: 0.35, badge: 0.6 } as Record<BodyKind, number>,
  gap: 14,
  iterations: 3,
  push: 0.3,
  kick: 0.06,
  growMs: 450,
  hubLeadMs: 260,
  petalStaggerMs: 70,
}

const GROW_REDUCED_MS = 250
const SWELL_MS = 700
const SWELL_AMOUNT = 0.12
const COLLIDE_MIN_SCALE = 0.25

export function createWorld(): World {
  return { bodies: new Map() }
}

export function syncWorld(w: World, specs: BodySpec[], now: number, rng: () => number = Math.random): void {
  const keep = new Set<string>()
  for (const spec of specs) {
    keep.add(spec.id)
    const existing = w.bodies.get(spec.id)
    if (existing) {
      Object.assign(existing, spec)
      continue
    }
    const body: Body = {
      ...spec,
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
    const p = spec.start ?? homeOf(w, body)
    body.x = p.x
    body.y = p.y
  }
  for (const id of [...w.bodies.keys()]) if (!keep.has(id)) w.bodies.delete(id)
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

export function stepWorld(w: World, dtFrames: number, now: number, opts: { reduced: boolean }): void {
  const { reduced } = opts
  const dt = Math.min(3, Math.max(0, dtFrames))
  const drift = reduced ? 0 : FEEL.drift
  const damp = reduced ? FEEL.dampReduced : FEEL.damp
  const t = now / 1000
  const bodies = [...w.bodies.values()]

  // Homes resolve against the parent's position before anyone moves this frame.
  const homes = bodies.map((b) => homeOf(w, b))
  bodies.forEach((b, i) => {
    if (b.pinned || now < b.bornAt + (b.delay ?? 0)) return
    const h = homes[i]
    const tx = h.x + Math.sin(t * FEEL.driftW[0] + b.ph1) * drift
    const ty = h.y + Math.cos(t * FEEL.driftW[1] + b.ph2) * drift
    const k = FEEL.k[b.kind]
    b.vx = (b.vx + (tx - b.x) * k) * damp
    b.vy = (b.vy + (ty - b.y) * k) * damp
    b.x += b.vx * dt
    b.y += b.vy * dt
  })

  const live = bodies.filter((b) => growScale(b, now, reduced) >= COLLIDE_MIN_SCALE)
  for (let it = 0; it < FEEL.iterations; it++) {
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const a = live[i]
        const c = live[j]
        if (a.ignore === c.id || c.ignore === a.id) continue
        const dx = c.x - a.x
        const dy = c.y - a.y
        const ox = (a.w + c.w) / 2 + FEEL.gap - Math.abs(dx)
        const oy = (a.h + c.h) / 2 + FEEL.gap - Math.abs(dy)
        if (ox <= 0 || oy <= 0) continue
        const ia = a.pinned ? 0 : FEEL.invMass[a.kind]
        const ic = c.pinned ? 0 : FEEL.invMass[c.kind]
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
}
