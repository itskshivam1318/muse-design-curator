import type { Point } from '../api'
import type { Bounds } from '../canvas/geometry'
import { createWorld, stepWorld, syncWorld, type Body } from './physics'
import type { Scene } from './scene'

export interface LivingWorld {
  sync(scene: Scene, now?: number): void
  body(id: string): Body | undefined
  /** Called after each step (one rAF); returns unsubscribe. */
  onFrame(fn: (now: number) => void): () => void
  /** Replaces the pinned set (selection). */
  setPinned(ids: Iterable<string>): void
  /** Grabbed bodies are pinned and follow dragBy. */
  grab(ids: string[]): void
  /** Moves every grabbed body to its grab-time position plus the total delta since grab. */
  dragBy(dx: number, dy: number): void
  /** Grabbed ids → centres at release; ungrabs (selection-pinned bodies stay pinned). */
  release(): Map<string, Point>
  /**
   * Puts a body at `centre`, at rest: a pinned body whose home moved (a remote move, an undo). A
   * grabbed body is left to the pointer.
   */
  place(id: string, centre: Point): void
  /** The clock the world steps and grows bodies by. */
  now(): number
  /** The keep swell / "already open" nudge. A body not synced yet (a take just kept) swells as it arrives. */
  pulse(id: string): void
  setReduced(r: boolean): void
  reduced(): boolean
  /**
   * Bodies whose centre is more than one viewport-diagonal outside the viewport sleep: they are
   * neither stepped nor collided. Before the first call nothing sleeps.
   */
  setViewport(b: Bounds): void
  start(): void
  stop(): void
}

export interface LivingWorldOpts {
  reduced: boolean
  now?: () => number
  schedule?: (cb: FrameRequestCallback) => number
  cancel?: (h: number) => void
}

const FRAME_MS = 1000 / 60
/** At most this many fixed steps per frame (after a stall the world catches up only so far). */
const MAX_STEPS = 3

export function createLivingWorld(opts: LivingWorldOpts): LivingWorld {
  const now = opts.now ?? (() => performance.now())
  const schedule = opts.schedule ?? ((cb) => requestAnimationFrame(cb))
  const cancel = opts.cancel ?? ((h) => cancelAnimationFrame(h))
  const world = createWorld()
  const subs = new Set<(now: number) => void>()
  const grabbed = new Map<string, Point>() // id → position at grab time
  let selection = new Set<string>()
  let reduced = opts.reduced
  let viewport: Bounds | null = null
  let handle: number | null = null
  let last = 0
  let pending = 0 // frames of time not yet stepped
  const pulses = new Set<string>() // pulsed before their body arrived

  const applyPins = (): void => {
    for (const b of world.bodies.values()) b.pinned = grabbed.has(b.id) || selection.has(b.id)
  }

  const awake = (b: Body): boolean => {
    if (!viewport) return true
    const m = Math.hypot(viewport.width, viewport.height)
    const cx = viewport.x + viewport.width / 2
    const cy = viewport.y + viewport.height / 2
    return Math.abs(b.x - cx) <= viewport.width / 2 + m && Math.abs(b.y - cy) <= viewport.height / 2 + m
  }

  const tick = (): void => {
    const t = now()
    // fixed steps of one 60 Hz frame: the push between bodies is per step, so a variable step would
    // move their resting point every frame (the board would never be still)
    pending = Math.min(MAX_STEPS, pending + (t - last) / FRAME_MS)
    last = t
    while (pending >= 1 - 1e-6) {
      stepWorld(world, 1, t, { reduced, awake })
      pending = Math.max(0, pending - 1)
    }
    for (const fn of [...subs]) fn(t)
    if (handle !== null) handle = schedule(tick)
  }

  return {
    sync(scene, at = now()) {
      syncWorld(world, scene.specs, at)
      for (const id of pulses) {
        const b = world.bodies.get(id)
        if (!b) continue
        b.pulseAt = at
        pulses.delete(id)
      }
      // Grabbed ids that vanished are dropped; the rest keep the pointer's position.
      for (const id of [...grabbed.keys()]) if (!world.bodies.has(id)) grabbed.delete(id)
      applyPins()
    },
    body: (id) => world.bodies.get(id),
    onFrame(fn) {
      subs.add(fn)
      return () => subs.delete(fn)
    },
    setPinned(ids) {
      selection = new Set(ids)
      applyPins()
    },
    grab(ids) {
      for (const id of ids) {
        const b = world.bodies.get(id)
        if (!b) continue
        grabbed.set(id, { x: b.x, y: b.y })
        b.vx = 0
        b.vy = 0
      }
      applyPins()
    },
    dragBy(dx, dy) {
      for (const [id, p] of grabbed) {
        const b = world.bodies.get(id)
        if (!b) continue
        b.x = p.x + dx
        b.y = p.y + dy
      }
    },
    release() {
      const out = new Map<string, Point>()
      for (const id of grabbed.keys()) {
        const b = world.bodies.get(id)
        if (!b) continue
        out.set(id, { x: b.x, y: b.y })
        b.vx = 0
        b.vy = 0
      }
      grabbed.clear()
      applyPins()
      return out
    },
    place(id, centre) {
      const b = world.bodies.get(id)
      if (!b || grabbed.has(id)) return
      b.x = centre.x
      b.y = centre.y
      b.vx = 0
      b.vy = 0
    },
    now,
    pulse(id) {
      const b = world.bodies.get(id)
      if (b) b.pulseAt = now()
      else pulses.add(id)
    },
    setReduced(r) {
      reduced = r
    },
    reduced: () => reduced,
    setViewport(b) {
      viewport = b
    },
    start() {
      if (handle !== null) return
      last = now()
      pending = 0
      handle = schedule(tick)
    },
    stop() {
      if (handle === null) return
      cancel(handle)
      handle = null
    },
  }
}
