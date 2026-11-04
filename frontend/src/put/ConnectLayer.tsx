/**
 * "Put into", on the board: the connect dot on a selected picture's right edge, the line dragged from it,
 * and the spots its end aims at on another picture (each part's region, or a ring at a point), with a
 * count by the line's end. Let go on a target, the line stays and its card opens on it; once put in,
 * a ghost holds the result's place until it lands. HTML over the canvas; only the dot, the card and a
 * failed ghost take the pointer.
 */
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { type AnalysisView, type Item, keys, type PartView, type Point, putInto } from '../api'
import { type Bounds, toCanvasPoint, toScreenPoint, type View } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { useLiveBounds } from '../living/useLiveBounds'
import type { LivingWorld } from '../living/world'
import { RegionOverlay } from '../map/RegionOverlay'
import { regionOf } from '../map/regions'
import { useAnalysis, useRegion } from '../queries'
import { cardPlace, PUT_CARD_H, PUT_CARD_ID, PUT_CARD_W } from './bodies'
import { GhostTile } from './GhostTile'
import { addGhost, useGhosts } from './ghosts'
import { placeCard } from './placeCard'
import { PutCard } from './PutCard'
import { aimAt, type Spot, toBody } from './spots'
import { type Connect, itemUnder, type Placed, type useConnect } from './useConnect'
import './put.css'

interface Props {
  boardId: string
  items: readonly Item[]
  view: View
  world: LivingWorld
  readOnly: boolean
  selectedIds: readonly string[]
  connect: ReturnType<typeof useConnect>
  /** The selection toolbar's size (canvas units, its gap included): the card opens clear of it. */
  toolbar?: { w: number; h: number }
  /** The open card's drawn size (screen px), for its body; null once it closes. */
  onCardSize?: (size: { width: number; height: number } | null) => void
}

const SPOKE_SAG = 22

export function ConnectLayer({ boardId, items, view, world, readOnly, selectedIds, connect, toolbar, onCardSize }: Props) {
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
  // a source gone (deleted, or removed from another tab) ends the line, drag or card; so does a target gone
  // under the open card: nothing is left behind, its body included
  const gone = (state.phase !== 'idle' && !byId.has(state.sourceId)) || (state.phase === 'card' && !byId.has(state.targetId))
  useEffect(() => {
    if (gone) cancel()
  }, [gone, cancel])

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
  // the card opens beside the target, clear of the source, and stays there; the line's end keeps to its spot
  const place = (line: { sourceId: string; targetId: string; at: Point }): Placed | null => {
    const s = liveBounds(line.sourceId)
    const t = liveBounds(line.targetId)
    if (!s || !t) return null
    return {
      cardAt: cardPlace(s, t, { w: PUT_CARD_W / view.scale, h: PUT_CARD_H / view.scale }, toolbar),
      endOn: { fx: (line.at.x - t.x) / t.width, fy: (line.at.y - t.y) / t.height },
    }
  }

  const ghosts = useGhosts(boardId)
  const targetBox = useLiveBounds(targetId ?? '') ?? (target ? itemBounds(target) : null)
  const start = sourceBox && toScreenPoint({ x: sourceBox.x + sourceBox.width, y: sourceBox.y + sourceBox.height / 2 }, view)
  const cardEnd =
    state.phase === 'card'
      ? state.endOn && targetBox
        ? { x: targetBox.x + state.endOn.fx * targetBox.width, y: targetBox.y + state.endOn.fy * targetBox.height }
        : state.end
      : null
  const endAt = state.phase === 'drag' ? state.at : cardEnd
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
          onPointerUp={() => connect.release(place)}
          onPointerCancel={() => connect.cancel()}
        />
      )}
      {state.phase === 'card' && source && target && (
        <CardOnLine
          key={`${state.sourceId}>${state.targetId}`}
          boardId={boardId}
          source={source}
          target={target}
          state={state}
          view={view}
          connect={connect}
          onSize={onCardSize}
        />
      )}
      {ghosts.map((g) => (
        <GhostTile key={g.jobId} ghost={g} view={view} />
      ))}
    </>
  )
}

type CardState = Extract<Connect, { phase: 'card' }>

/** The card where its body is (placed when the line is let go; it gives way to what it meets, and its home holds it there). */
function CardOnLine({ boardId, source, target, state, view, connect, onSize }: {
  boardId: string
  source: Item
  target: Item
  state: CardState
  view: View
  connect: ReturnType<typeof useConnect>
  onSize?: (size: { width: number; height: number } | null) => void
}) {
  const live = useLiveBounds(PUT_CARD_ID)
  const centre = live ? { x: live.x + live.width / 2, y: live.y + live.height / 2 } : state.cardAt
  const at = toScreenPoint(centre, view)
  const anchor = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: PUT_CARD_W, h: PUT_CARD_H })
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const reportSize = useCallback((s: { width: number; height: number } | null) => {
    if (s) setSize((p) => (p.w === s.width && p.h === s.height ? p : { w: s.width, h: s.height }))
    onSize?.(s)
  }, [onSize])
  // the body's spot is where the card would sit; the card keeps off the agent card and the screen edge
  useLayoutEffect(() => {
    const box = anchor.current?.parentElement?.getBoundingClientRect()
    if (!box || !box.width || !box.height) return
    const agent = document.querySelector('.agent-card')?.getBoundingClientRect()
    const avoid = agent ? [{ left: agent.left - box.left, top: agent.top - box.top, right: agent.right - box.left, bottom: agent.bottom - box.top }] : []
    setPos(placeCard({ x: at.x - size.w / 2, y: at.y - size.h / 2 }, size, { w: box.width, h: box.height }, avoid))
  }, [at.x, at.y, size])
  const submit = async (words: string) => {
    const w = words.trim()
    const body = { source_id: source.id, spots: toBody(state.spots, state.off), ...(w ? { words: w } : {}) }
    const r = await putInto(target.id, body)
    addGhost({ jobId: r.job_id, boardId, targetId: target.id, x: r.x, y: r.y, w: r.w, h: r.h, request: { targetId: target.id, body }, error: null })
    connect.cancel()
  }
  return (
    <div ref={anchor} className="put-card-anchor" style={{ left: pos?.x ?? at.x - size.w / 2, top: pos?.y ?? at.y - size.h / 2, width: PUT_CARD_W }}>
      <PutCard
        source={source}
        target={target}
        spots={state.spots}
        off={state.off}
        onToggle={connect.toggle}
        onCancel={connect.cancel}
        onSubmit={submit}
        onSize={reportSize}
      />
    </div>
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
