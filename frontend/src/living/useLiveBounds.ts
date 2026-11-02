import { useLayoutEffect, useState } from 'react'
import type { Bounds } from '../canvas/geometry'
import { useLivingWorld } from './useLiving'
import type { LivingWorld } from './world'

/** Moves under this (canvas units) do not re-render. */
const STILL = 0.25

function read(world: LivingWorld, ids: readonly string[]): Bounds[] | null {
  const out: Bounds[] = []
  for (const id of ids) {
    const b = world.body(id)
    if (!b) return null
    out.push({ x: b.x - b.w / 2, y: b.y - b.h / 2, width: b.w, height: b.h })
  }
  return out
}

const near = (a: Bounds[] | null, b: Bounds[] | null): boolean =>
  a === b ||
  (!!a &&
    !!b &&
    a.length === b.length &&
    a.every(
      (p, i) =>
        Math.abs(p.x - b[i].x) < STILL &&
        Math.abs(p.y - b[i].y) < STILL &&
        Math.abs(p.width - b[i].width) < STILL &&
        Math.abs(p.height - b[i].height) < STILL,
    ))

/**
 * Where several bodies are now (top-left and size, canvas units), for HTML that must follow them: null
 * until every one is in the world. Re-renders at most once per frame, and only when one moved.
 */
export function useLiveBoxes(ids: readonly string[]): Bounds[] | null {
  const world = useLivingWorld()
  const key = ids.join('\n')
  const [boxes, setBoxes] = useState(() => read(world, ids))
  // a layout effect: when the ids change, the new boxes are in before the next paint
  useLayoutEffect(() => {
    const list = key ? key.split('\n') : []
    const tick = () => {
      const next = read(world, list)
      setBoxes((prev) => (near(prev, next) ? prev : next))
    }
    tick()
    return world.onFrame(tick)
  }, [world, key])
  return boxes
}

/** Where one body is now (see useLiveBoxes); null while it is not in the world. */
export function useLiveBounds(id: string): Bounds | null {
  return useLiveBoxes([id])?.[0] ?? null
}
