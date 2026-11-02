import { describe, expect, it } from 'vitest'
import { createLivingWorld, type LivingWorld } from './world'
import type { BodySpec } from './physics'
import type { Scene } from './scene'

const item = (id: string, x: number, y: number): BodySpec => ({ id, kind: 'item', w: 100, h: 80, home: { kind: 'abs', x, y } })
const scene = (...specs: BodySpec[]): Scene => ({ specs, edges: [], flowers: [], docked: new Map() })

function rig() {
  let t = 1000
  let cb: FrameRequestCallback | null = null
  const world = createLivingWorld({
    reduced: true,
    now: () => t,
    schedule: (f) => ((cb = f), 1),
    cancel: () => {
      cb = null
    },
  })
  const frame = (): void => {
    t += 1000 / 60
    const f = cb
    cb = null
    f?.(t)
  }
  return { world, frame, pending: () => cb !== null }
}

describe('living world', () => {
  it('sync during a grab leaves grabbed bodies where the pointer has them', () => {
    const { world } = rig()
    world.sync(scene(item('a', 0, 0)))
    world.grab(['a'])
    world.dragBy(50, 20)
    world.sync(scene(item('a', 0, 0), item('b', 500, 0)))
    expect(world.body('a')).toMatchObject({ x: 50, y: 20, pinned: true })
  })

  it('dragBy moves every grabbed body by the same delta', () => {
    const { world } = rig()
    world.sync(scene(item('a', 0, 0), item('b', 300, 100)))
    world.grab(['a', 'b'])
    world.dragBy(10, 5)
    world.dragBy(30, -5)
    expect(world.body('a')).toMatchObject({ x: 30, y: -5 })
    expect(world.body('b')).toMatchObject({ x: 330, y: 95 })
  })

  it('release returns centres and unpins', () => {
    const { world } = rig()
    world.sync(scene(item('a', 0, 0)))
    world.grab(['a'])
    world.dragBy(7, 9)
    expect(world.release()).toEqual(new Map([['a', { x: 7, y: 9 }]]))
    expect(world.body('a')!.pinned).toBe(false)
  })

  it('release keeps selection-pinned bodies pinned', () => {
    const { world } = rig()
    world.sync(scene(item('a', 0, 0)))
    world.setPinned(['a'])
    world.grab(['a'])
    world.release()
    expect(world.body('a')!.pinned).toBe(true)
  })

  it('selected bodies are pinned', () => {
    const { world, frame } = rig()
    world.sync(scene(item('a', 0, 0), item('b', 60, 0)))
    world.setPinned(['a'])
    world.start()
    for (let i = 0; i < 60; i++) frame()
    expect(world.body('a')).toMatchObject({ x: 0, y: 0 })
    expect(world.body('b')!.x).toBeGreaterThan(60)
  })

  it('onFrame subscribers run once per scheduled frame and stop after stop()', () => {
    const { world, frame, pending } = rig()
    let n = 0
    const off = world.onFrame(() => n++)
    world.sync(scene(item('a', 0, 0)))
    world.start()
    frame()
    frame()
    expect(n).toBe(2)
    world.stop()
    expect(pending()).toBe(false)
    frame()
    expect(n).toBe(2)
    off()
  })

  it('offscreen bodies sleep', () => {
    const { world, frame } = rig()
    const a = item('a', 0, 0)
    world.sync(scene({ ...a, start: { x: 5000, y: 0 } } as BodySpec))
    world.setViewport({ x: 0, y: 0, width: 800, height: 600 })
    world.start()
    for (let i = 0; i < 10; i++) frame()
    expect(world.body('a')!.x).toBe(5000)
    world.setViewport({ x: 4600, y: -300, width: 800, height: 600 })
    for (let i = 0; i < 10; i++) frame()
    expect(world.body('a')!.x).toBeLessThan(5000)
  })
})

export type { LivingWorld }
