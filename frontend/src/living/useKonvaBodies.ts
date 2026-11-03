import type Konva from 'konva'
import { type RefObject, useEffect } from 'react'
import type { Bounds } from '../canvas/geometry'
import { lineagePoints } from '../canvas/nodeProps'
import { growScale } from './physics'
import type { LivingWorld } from './world'

const r2 = (n: number) => Math.round(n * 100) / 100

/**
 * Each frame, puts the layer's board nodes where the world has their bodies, without a React render:
 * a node whose id is a body's (an item), or that names one in its `body` attr (what is drawn around an
 * item), goes to the body's top-left at its grow scale (growing about its centre); a `living-link`
 * line is redrawn between the two bodies in its `link` attr. The node Konva is dragging is left alone.
 * A node laid out at another width than its body's (its `natW` attr: a take docking or undocking eases
 * between sizes, a note is laid out at the note width) is scaled to the body's width as it eases.
 */
export function useKonvaBodies(world: LivingWorld, layerRef: RefObject<Konva.Layer | null>): void {
  useEffect(() => {
    const boxOf = (id: string): Bounds | null => {
      const b = world.body(id)
      return b ? { x: b.x - b.w / 2, y: b.y - b.h / 2, width: b.w, height: b.h } : null
    }
    const write = (now: number): void => {
      const layer = layerRef.current
      if (!layer) return
      let changed = false // at rest nothing moves: no redraw
      for (const node of layer.getChildren()) {
        const link = node.attrs.link as [string, string] | undefined
        if (link) {
          const [from, to] = link.map(boxOf)
          if (!from || !to) continue
          const points = lineagePoints(from, to).map(r2)
          const line = node as Konva.Line
          const old = line.points()
          if (old.length !== points.length || old.some((v, i) => v !== points[i])) {
            line.points(points)
            changed = true
          }
          continue
        }
        const b = world.body((node.attrs.body as string | undefined) ?? node.id())
        if (!b || node.isDragging()) continue
        // to 0.01: a settled board compares equal and is not redrawn
        const grow = r2(Math.max(growScale(b, now, world.reduced()), 0.001)) // a zero scale cannot be hit-tested
        const natW = node.attrs.natW as number | undefined
        const s = natW ? Math.round(((grow * b.w) / natW) * 1e4) / 1e4 : grow
        const x = r2(b.x - (b.w * grow) / 2)
        const y = r2(b.y - (b.h * grow) / 2)
        if (node.x() !== x || node.y() !== y || node.scaleX() !== s || node.scaleY() !== s) {
          node.position({ x, y })
          node.scale({ x: s, y: s })
          changed = true
        }
      }
      if (changed) layer.batchDraw()
    }
    write(world.now())
    return world.onFrame(write)
  }, [world, layerRef])
}
