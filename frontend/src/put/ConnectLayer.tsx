/**
 * "Put into", on the board: the connect dot on a selected picture's right edge, the line dragged from it,
 * and the spots its end aims at on another picture (each part's region, or a ring at a point), with a
 * count by the line's end. HTML over the canvas; only the dot takes the pointer.
 */
import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { type AnalysisView, type Item, keys, type PartView, type Point } from '../api'
import { type Bounds, toCanvasPoint, toScreenPoint, type View } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { useLiveBounds } from '../living/useLiveBounds'
import type { LivingWorld } from '../living/world'
import { RegionOverlay } from '../map/RegionOverlay'
import { regionOf } from '../map/regions'
import { useAnalysis, useRegion } from '../queries'
import { aimAt, type Spot } from './spots'
import { itemUnder, type useConnect } from './useConnect'
import './put.css'

interface Props {
  items: readonly Item[]
  view: View
  world: LivingWorld
  readOnly: boolean
  selectedIds: readonly string[]
  connect: ReturnType<typeof useConnect>
}

const SPOKE_SAG = 22

export function ConnectLayer({ items, view, world, readOnly, selectedIds, connect }: Props) {
  const qc = useQueryClient()
  const { state } = connect
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items])
  const sole = selectedIds.length === 1 ? byId.get(selectedIds[0]) : undefined
  const canStart = !!sole && sole.kind === 'image' && !sole.staged && !readOnly && !world.grabbing()
  // a held line keeps its dot (it holds the pointer) whatever else changes; a line starts at its source's dot
  const dotItem = state.phase === 'drag' ? byId.get(state.sourceId) : canStart ? sole : undefined
  const source = state.phase === 'idle' ? dotItem : byId.get(state.sourceId)
  const sourceBox = useLiveBounds(source?.id ?? '') ?? (source ? itemBounds(source) : null)
  const targetId = state.phase === 'idle' ? null : state.targetId
  const target = targetId ? byId.get(targetId) : undefined

  const liveBounds = (id: string): Bounds | null => {
    const b = world.body(id)
    if (b) return { x: b.x - b.w / 2, y: b.y - b.h / 2, width: b.w, height: b.h }
    const i = byId.get(id)
    return i ? itemBounds(i) : null
  }
  const aim = (p: Point): { targetId: string | null; spots: Spot[] } => {
    if (state.phase !== 'drag') return { targetId: null, spots: [] }
    const t = itemUnder(items, liveBounds, p, state.sourceId)
    const b = t && liveBounds(t.id)
    if (!t || !b) return { targetId: null, spots: [] }
    const analysis = qc.getQueryData<AnalysisView>(keys.analysis(t.id))
    return { targetId: t.id, spots: aimAt(analysis, (p.x - b.x) / b.width, (p.y - b.y) / b.height) }
  }

  // the target's analysis: asked for when the line enters it, and aimed with again once it arrives
  const last = useRef<Point | null>(null)
  const targetAnalysis = useAnalysis(state.phase === 'drag' ? targetId : null).data
  const reaim = useRef(() => {})
  useEffect(() => {
    reaim.current = () => last.current && connect.move(last.current, aim(last.current))
  })
  useEffect(() => {
    if (targetAnalysis) reaim.current()
  }, [targetAnalysis])

  const active = state.phase !== 'idle'
  const cancel = connect.cancel
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, cancel])

  const toCanvas = (e: ReactPointerEvent<HTMLElement>): Point => {
    const r = e.currentTarget.parentElement?.getBoundingClientRect()
    return toCanvasPoint({ x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) }, view)
  }
  const onDown = (e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0 || !dotItem) return
    e.preventDefault()
    e.stopPropagation()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    last.current = null
    connect.start(dotItem.id, toCanvas(e))
  }
  const onMove = (e: ReactPointerEvent<HTMLElement>) => {
    if (state.phase !== 'drag') return
    const p = toCanvas(e)
    last.current = p
    connect.move(p, aim(p))
  }

  const start = sourceBox && toScreenPoint({ x: sourceBox.x + sourceBox.width, y: sourceBox.y + sourceBox.height / 2 }, view)
  const endAt = state.phase === 'drag' ? state.at : state.phase === 'card' ? state.end : null
  const end = endAt && toScreenPoint(endAt, view)
  const spots = state.phase === 'idle' ? [] : state.spots
  const off = state.phase === 'card' ? state.off : null

  return (
    <>
      {start && end && (
        <svg className="put-line-layer" aria-hidden="true">
          <path className="put-line" d={curve(start, end)} />
        </svg>
      )}
      {target &&
        spots.map((s, i) =>
          off?.has(i) ? null : s.kind === 'part' ? (
            <PartHighlight key={`part-${s.part.key}`} target={target} part={s.part} view={view} />
          ) : (
            <PointRing key={`point-${i}`} target={target} fx={s.fx} fy={s.fy} view={view} />
          ),
        )}
      {state.phase === 'drag' && end && spots.length > 0 && (
        <div className="put-count" style={{ left: end.x, top: end.y }}>
          {spots.length === 1 ? '1 spot' : `${spots.length} spots`}
        </div>
      )}
      {dotItem && start && (
        <button
          type="button"
          className="put-dot"
          aria-label="Connect to another picture"
          style={{ left: start.x, top: start.y }}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={() => connect.release()}
          onPointerCancel={() => connect.cancel()}
        />
      )}
    </>
  )
}

/** The spoke's look: a solid curve with a slight sag. */
function curve(a: Point, b: Point): string {
  const r2 = (n: number) => Math.round(n * 100) / 100
  const sag = Math.min(SPOKE_SAG, Math.hypot(b.x - a.x, b.y - a.y) * 0.1)
  return `M${r2(a.x)},${r2(a.y)} Q${r2((a.x + b.x) / 2)},${r2((a.y + b.y) / 2 + sag)} ${r2(b.x)},${r2(b.y)}`
}

/** An aimed part's region on the target, sharpening from box to mask as its region arrives. */
function PartHighlight({ target, part, view }: { target: Item; part: PartView; view: View }) {
  const b = useLiveBounds(target.id) ?? itemBounds(target)
  const q = useRegion(target.id, part.key, true)
  const r = regionOf(part, q.data, q.isPending)
  if (!r) return null
  return <RegionOverlay item={{ ...target, x: b.x, y: b.y }} region={r.region} loading={r.loading} view={view} />
}

/** "Here": a small ring at the exact point aimed at. */
function PointRing({ target, fx, fy, view }: { target: Item; fx: number; fy: number; view: View }) {
  const b = useLiveBounds(target.id) ?? itemBounds(target)
  const p = toScreenPoint({ x: b.x + fx * b.width, y: b.y + fy * b.height }, view)
  return <div className="put-ring" style={{ left: p.x, top: p.y }} aria-hidden="true" />
}
