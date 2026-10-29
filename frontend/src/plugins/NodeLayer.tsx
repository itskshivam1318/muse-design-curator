/**
 * The board's plugin nodes over the canvas: one card per node, the wiring lines (inputs into the
 * node, the node out to what its latest run made) and a notice for node actions that failed
 * elsewhere.
 */
import { type WheelEvent, useEffect, useMemo } from 'react'
import type { Item } from '../api'
import { itemBounds, lineagePoints } from '../canvas/nodeProps'
import { type Bounds, toScreenPoint, type View } from '../canvas/geometry'
import { useDemo } from '../demo'
import { useNodes, usePlugins } from '../queries'
import { NodeCard } from './NodeCard'
import { nodeBounds } from './nodeLogic'
import './plugins.css'
import { nodeNoticeStore, useDropTarget, useNodeNotice, viewportStore } from './stores'

interface Props {
  boardId: string
  /** The canvas's visible items, as drawn (a dragged item carries its lines along). */
  items: readonly Item[]
  view: View
  size: { width: number; height: number }
  readOnly?: boolean
  /** Wheel over a card pans or zooms the canvas like anywhere else. */
  onWheel?: (e: WheelEvent) => void
}

function path(points: number[], view: View): string {
  const p = (i: number) => toScreenPoint({ x: points[i], y: points[i + 1] }, view)
  const [a, b, c, d] = [p(0), p(2), p(4), p(6)]
  return `M${a.x} ${a.y}C${b.x} ${b.y} ${c.x} ${c.y} ${d.x} ${d.y}`
}

export function NodeLayer({ boardId, items, view, size, readOnly = false, onWheel }: Props) {
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
  const pluginById = useMemo(() => new Map((plugins ?? []).map((p) => [p.id, p])), [plugins])

  if (!pluginsEnabled || !nodes) return null

  const lines: { id: string; d: string; out: boolean }[] = []
  for (const n of nodes.nodes) {
    const nb: Bounds = nodeBounds(n)
    for (const id of n.input_item_ids) {
      const it = byId.get(id)
      if (it) lines.push({ id: `${n.id}-in-${id}`, d: path(lineagePoints(itemBounds(it), nb), view), out: false })
    }
    const run = nodes.runs[n.id]
    for (const id of run?.output?.created_item_ids ?? []) {
      const it = byId.get(id)
      if (it && it.generation?.run_id === run?.id)
        lines.push({ id: `${n.id}-out-${id}`, d: path(lineagePoints(nb, itemBounds(it)), view), out: true })
    }
  }

  return (
    <div className="node-layer">
      {lines.length > 0 && (
        <svg className="node-lines" width={size.width} height={size.height} aria-hidden="true">
          {lines.map((l) => (
            <path key={l.id} d={l.d} className={l.out ? 'is-out' : undefined} />
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
