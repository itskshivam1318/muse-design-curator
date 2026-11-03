/**
 * The board's plugin nodes over the canvas: one card per node, the wiring lines (inputs into the
 * node, the node out to what its latest run made) and a notice for node actions that failed
 * elsewhere.
 */
import { type WheelEvent, useEffect, useMemo, useRef } from 'react'
import type { Item } from '../api'
import { itemBounds, lineagePoints } from '../canvas/nodeProps'
import { type Bounds, toScreenPoint, type View } from '../canvas/geometry'
import { useDemo } from '../demo'
import { writeAttr } from '../living/writeAttr'
import type { LivingWorld } from '../living/world'
import { useNodes, usePlugins } from '../queries'
import { NodeCard } from './NodeCard'
import { nodeBounds } from './nodeLogic'
import './plugins.css'
import { nodeNoticeStore, useDropTarget, useNodeNotice, viewportStore } from './stores'

interface Props {
  boardId: string
  /** The canvas's visible items. */
  items: readonly Item[]
  /** The living board: wires follow where its items' bodies are now, every frame. */
  world?: LivingWorld
  view: View
  size: { width: number; height: number }
  readOnly?: boolean
  /** Wheel over a card pans or zooms the canvas like anywhere else. */
  onWheel?: (e: WheelEvent) => void
}

const r2 = (n: number) => Math.round(n * 100) / 100

/** The wire's path, to 0.01px (a wire at rest reads the same every frame and is not rewritten). */
function path(points: number[], view: View): string {
  const p = (i: number) => {
    const s = toScreenPoint({ x: points[i], y: points[i + 1] }, view)
    return { x: r2(s.x), y: r2(s.y) }
  }
  const [a, b, c, d] = [p(0), p(2), p(4), p(6)]
  return `M${a.x} ${a.y}C${b.x} ${b.y} ${c.x} ${c.y} ${d.x} ${d.y}`
}

type Wire = { id: string; d: string; out: boolean; itemId: string; node: Bounds }

export function NodeLayer({ boardId, items, view, size, readOnly = false, onWheel, world }: Props) {
  const { pluginsEnabled } = useDemo()
  const nodes = useNodes(boardId).data
  const plugins = usePlugins().data
  const dropTarget = useDropTarget()
  const notice = useNodeNotice()

  useEffect(() => {
    viewportStore.set({ view, width: size.width, height: size.height })
  }, [view, size.width, size.height])
  useEffect(() => () => viewportStore.set(null), [])
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => nodeNoticeStore.set(null), 6000)
    return () => clearTimeout(t)
  }, [notice])

  const byId = useMemo(() => new Map(items.filter((i) => !i.staged).map((i) => [i.id, i])), [items])
  const paths = useRef(new Map<string, { el: SVGPathElement; wire: Wire }>())
  // each frame, a wire runs from where its item's body is now (an item rests off its stored spot)
  useEffect(() => {
    if (!world) return
    const write = (): void => {
      for (const { el, wire: w } of paths.current.values()) {
        const b = world.body(w.itemId)
        if (!b) continue
        const box: Bounds = { x: b.x - b.w / 2, y: b.y - b.h / 2, width: b.w, height: b.h }
        writeAttr(el, 'd', path(w.out ? lineagePoints(w.node, box) : lineagePoints(box, w.node), view))
      }
    }
    write()
    return world.onFrame(write)
  }, [world, view])
  const pluginById = useMemo(() => new Map((plugins ?? []).map((p) => [p.id, p])), [plugins])

  if (!pluginsEnabled || !nodes) return null

  const lines: Wire[] = []
  for (const n of nodes.nodes) {
    const nb: Bounds = nodeBounds(n)
    for (const id of n.input_item_ids) {
      const it = byId.get(id)
      if (it) lines.push({ id: `${n.id}-in-${id}`, d: path(lineagePoints(itemBounds(it), nb), view), out: false, itemId: id, node: nb })
    }
    const run = nodes.runs[n.id]
    for (const id of run?.output?.created_item_ids ?? []) {
      const it = byId.get(id)
      if (it && it.generation?.run_id === run?.id)
        lines.push({ id: `${n.id}-out-${id}`, d: path(lineagePoints(nb, itemBounds(it)), view), out: true, itemId: id, node: nb })
    }
  }

  return (
    <div className="node-layer">
      {lines.length > 0 && (
        <svg className="node-lines" width={size.width} height={size.height} aria-hidden="true">
          {lines.map((l) => (
            <path
              key={l.id}
              ref={(el) => {
                if (el) paths.current.set(l.id, { el, wire: l })
                else paths.current.delete(l.id)
              }}
              d={l.d}
              className={l.out ? 'is-out' : undefined}
            />
          ))}
        </svg>
      )}
      {nodes.nodes.map((n) => (
        <NodeCard
          key={n.id}
          boardId={boardId}
          node={n}
          plugin={pluginById.get(n.plugin_id)}
          run={nodes.runs[n.id]}
          items={byId}
          view={view}
          readOnly={readOnly}
          dropTarget={dropTarget === n.id}
          onWheel={onWheel}
        />
      ))}
      {notice && (
        <p className="toast error node-notice" role="alert">
          {notice}
        </p>
      )}
    </div>
  )
}
