/**
 * The lines between living bodies (one SVG in canvas units, under the flowers and callouts): a dashed
 * stem from each flower's source to its hub, a spoke from each hub to its petals and docked takes.
 * Each frame writes every path's `d` from where the bodies are, bending it against their motion, so
 * a flower stays connected wherever it floats. Leaders to callouts are the callouts' own.
 */
import { useEffect, useRef } from 'react'
import type { Point } from '../api'
import type { View } from '../canvas/geometry'
import { type Body, growScale } from './physics'
import type { Edge, EdgeEnd, Scene } from './scene'
import { useLivingWorld } from './useLiving'
import { writeAttr } from './writeAttr'

const STEM_BEND = 40
const SPOKE_BEND = 22

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const r2 = (n: number) => Math.round(n * 100) / 100

/** Where a ray from `b`'s centre toward `p` leaves `b`. */
function edgeToward(b: Body, p: Point): Point {
  const dx = p.x - b.x
  const dy = p.y - b.y
  const s = Math.min(Math.abs(b.w / 2 / (dx || 1e-6)), Math.abs(b.h / 2 / (dy || 1e-6)))
  return { x: b.x + dx * s, y: b.y + dy * s }
}

/**
 * An edge's end on its body: its anchor, else the centre of a hub, petal or badge (drawn over the line),
 * else where the body's edge faces `toward` (an item, a take or a callout).
 */
function endPoint(b: Body, end: EdgeEnd, toward: Point): Point {
  if (end.anchor) return { x: b.x - b.w / 2 + end.anchor.fx * b.w, y: b.y - b.h / 2 + end.anchor.fy * b.h }
  if (b.kind === 'hub' || b.kind === 'petal' || b.kind === 'badge') return { x: b.x, y: b.y }
  return edgeToward(b, toward)
}

/** The edges drawn here: every one but the leaders. */
const drawn = (scene: Scene): Edge[] => scene.edges.filter((e) => e.kind !== 'leader')
/** A stem leaving an item (not a callout) gets an anchor dot where it leaves. */
const dotted = (e: Edge) => e.kind === 'stem' && !e.from.body.startsWith('callout:')

export function Edges({ scene, view }: { scene: Scene; view: View }) {
  const world = useLivingWorld()
  const paths = useRef(new Map<string, SVGPathElement>())
  const dots = useRef(new Map<string, SVGCircleElement>())

  useEffect(() => {
    const edges = drawn(scene)
    const write = (now: number): void => {
      const reduced = world.reduced()
      for (const e of edges) {
        const path = paths.current.get(e.id)
        if (!path) continue
        const from = world.body(e.from.body)
        const to = world.body(e.to.body)
        const dot = dots.current.get(e.id)
        if (!from || !to) {
          writeAttr(path, 'opacity', '0')
          if (dot) writeAttr(dot, 'opacity', '0')
          continue
        }
        const a = endPoint(from, e.from, to)
        const b = endPoint(to, e.to, from)
        const grown = clamp(growScale(to, now, reduced), 0, 1)
        if (e.kind === 'spoke') {
          const bx = clamp((to.vx - from.vx) * -9, -SPOKE_BEND, SPOKE_BEND)
          const by = clamp((to.vy - from.vy) * -9, -SPOKE_BEND, SPOKE_BEND)
          const mx = (a.x + b.x) / 2 + bx
          const my = (a.y + b.y) / 2 + by
          writeAttr(path, 'd', `M${r2(a.x)},${r2(a.y)} Q${r2(mx)},${r2(my)} ${r2(b.x)},${r2(b.y)}`)
          writeAttr(path, 'opacity', String(e.kept ? 0.9 : 0.55 * grown))
        } else {
          const bx = clamp(-to.vx * 10, -STEM_BEND, STEM_BEND)
          const by = clamp(-to.vy * 10, -STEM_BEND, STEM_BEND)
          // leave the source outward from its centre, arrive at the hub against its motion
          const c1 = { x: a.x + (a.x - from.x) * 0.35, y: a.y + (a.y - from.y) * 0.35 }
          const c2 = { x: b.x + bx - (b.x - a.x) * 0.25, y: b.y + by - (b.y - a.y) * 0.25 }
          writeAttr(path, 'd', `M${r2(a.x)},${r2(a.y)} C${r2(c1.x)},${r2(c1.y)} ${r2(c2.x)},${r2(c2.y)} ${r2(b.x)},${r2(b.y)}`)
          writeAttr(path, 'opacity', String(grown))
        }
        if (dot) {
          writeAttr(dot, 'cx', String(r2(a.x)))
          writeAttr(dot, 'cy', String(r2(a.y)))
          writeAttr(dot, 'opacity', String(grown))
        }
      }
    }
    write(world.now())
    return world.onFrame(write)
  }, [world, scene])

  const edges = drawn(scene)
  return (
    <div className="edge-layer" aria-hidden="true">
      <div className="edge-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        <svg className="flower-lines" width="1" height="1">
          {edges.map((e) => (
            <path
              key={e.id}
              ref={(el) => {
                if (el) paths.current.set(e.id, el)
                else paths.current.delete(e.id)
              }}
              data-edge-kind={e.kind}
              data-edge-id={e.id}
              className={e.kind === 'stem' ? 'flower-stem' : e.kept ? 'flower-spoke is-kept' : 'flower-spoke'}
              fill="none"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {edges
            .filter(dotted)
            .map((e) => (
              <circle
                key={`dot:${e.id}`}
                ref={(el) => {
                  if (el) dots.current.set(e.id, el)
                  else dots.current.delete(e.id)
                }}
                className="flower-root"
                r={4.5 / view.scale}
              />
            ))}
        </svg>
      </div>
    </div>
  )
}
