import type Konva from 'konva'
import { type RefObject, useEffect } from 'react'
import type { Bounds } from '../canvas/geometry'
import { lineagePoints } from '../canvas/nodeProps'
import { growScale } from './physics'
import type { LivingWorld } from './world'

/**
 * Each frame, puts the layer's board nodes where the world has their bodies, without a React render:
 * a node whose id is a body's (an item), or that names one in its `body` attr (what is drawn around an
 * item), goes to the body's top-left at its grow scale (growing about its centre); a `living-link`
 * line is redrawn between the two bodies in its `link` attr. The node Konva is dragging is left alone.
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
      for (const node of layer.getChildren()) {
        const link = node.attrs.link as [string, string] | undefined
        if (link) {
          const [from, to] = link.map(boxOf)
          if (from && to) (node as Konva.Line).points(lineagePoints(from, to))
          continue
        }
        const b = world.body((node.attrs.body as string | undefined) ?? node.id())
        if (!b || node.isDragging()) continue
        const s = Math.max(growScale(b, now, world.reduced()), 0.001) // a zero scale cannot be hit-tested
        node.position({ x: b.x - (b.w * s) / 2, y: b.y - (b.h * s) / 2 })
        node.scale({ x: s, y: s })
      }
      layer.batchDraw()
    }
    write(world.now())
    return world.onFrame(write)
  }, [world, layerRef])
}
