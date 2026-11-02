/**
 * Exploration flowers over the canvas (HTML in canvas units, like the callouts): a hub, the options
 * around it as petals, each placed by its body in the living world (the lines are `Edges`). A petal
 * opens its card; the hub collapses the flower to a badge. A kept option has no petal: its take is
 * docked in the ring in its place.
 */
import { type WheelEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ExploreOption, Item, Point } from '../api'
import type { View } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { resultCheck } from '../explore/verdict'
import type { FlowerModel } from '../living/scene'
import { useBodyElement, useLivingWorld } from '../living/useLiving'
import { useItems } from '../queries'
import { setCollapsed } from './collapse'
import { clampCard, placeBeside } from './layout'
import { PetalCard, ResultPreview } from './PetalCard'
import { isKept, resultOf } from './results'

type PetalState = 'note' | 'rendered' | 'kept' | 'drifted'

function petalState(option: ExploreOption, result: Item | undefined, label: string): PetalState {
  if (isKept(option)) return 'kept'
  if (!result) return 'note'
  return resultCheck(result.check, label, option.name).tone === 'drift' ? 'drifted' : 'rendered'
}

interface FlowerProps {
  model: FlowerModel
  /** The source item (a text result's change is marked against it). */
  source?: Item
  /** Every item, staged results included. */
  byId?: ReadonlyMap<string, Item>
  openOption?: string | null
  onOpenOption?: (optionId: string) => void
  onToggle?: () => void
}

/** A ref whose element the living world places (its body `id`'s top-left, size and grow scale). */
function usePlaced<T extends HTMLElement>(id: string) {
  const ref = useRef<T>(null)
  useBodyElement(id, ref)
  return ref
}

export function Flower({ model, source, byId = new Map(), openOption = null, onOpenOption, onToggle }: FlowerProps) {
  const hubRef = usePlaced<HTMLDivElement & HTMLButtonElement>(model.hubId)
  const n = model.options.length
  const k = model.options.filter(isKept).length
  const summary = `${n} options · ${k} kept`
  if (model.collapsed) {
    const text = `${model.label} · ${summary}`
    return (
      <div role="group" aria-label={`${model.label} flower`} data-exploration-id={model.id}>
        <button ref={hubRef} type="button" className="flower-badge" aria-label={text} onClick={onToggle}>
          {text}
        </button>
      </div>
    )
  }
  return (
    <div role="group" aria-label={`${model.label} flower`} data-exploration-id={model.id}>
      <div ref={hubRef} className="flower-hub">
        <span className="flower-hub-label">{model.label}</span>
        <span className="flower-hub-sub">{summary}</span>
        <button type="button" className="flower-collapse" aria-label={`Collapse ${model.label}`} title="Collapse" onClick={onToggle}>
          –
        </button>
      </div>
      {model.options.map((o) =>
        isKept(o) ? null : (
          <Petal
            key={o.id}
            option={o}
            label={model.label}
            source={source}
            byId={byId}
            open={openOption === o.id}
            onOpen={() => onOpenOption?.(o.id)}
          />
        ),
      )}
    </div>
  )
}

interface PetalProps {
  option: ExploreOption
  /** The flower's dimension label (a result's check is read against it). */
  label: string
  source?: Item
  byId: ReadonlyMap<string, Item>
  open: boolean
  onOpen: () => void
}

function Petal({ option: o, label, source, byId, open, onOpen }: PetalProps) {
  const ref = usePlaced<HTMLButtonElement>(`petal:${o.id}`)
  const result = resultOf(o, byId)
  const state = petalState(o, result, label)
  const cls = ['petal', `is-${state}`, open && 'is-open'].filter(Boolean).join(' ')
  const showResult = state !== 'note' && result && source
  return (
    <button
      ref={ref}
      type="button"
      className={cls}
      data-testid="petal"
      data-option-id={o.id}
      aria-pressed={open}
      aria-label={`${o.name} · ${o.distance}${state === 'note' ? '' : ` · ${state}`}`}
      onClick={onOpen}
    >
      {showResult ? (
        <ResultPreview result={result} source={source} alt="" />
      ) : (
        <>
          <span className="petal-name">{o.name}</span>
          <span className="petal-tag" data-distance={o.distance}>
            {o.distance}
          </span>
        </>
      )}
      {o.status === 'visualizing' && (
        <span className="petal-busy">
          <span className="spinner" aria-hidden="true" />
        </span>
      )}
    </button>
  )
}

interface LayerProps {
  boardId: string
  /** The board's items as drawn (not staged): the flowers' sources. */
  items: readonly Item[]
  view: View
  /** The scene's flowers. */
  flowers: readonly FlowerModel[]
  locked?: boolean
  /** Wheel over a flower pans or zooms the canvas like anywhere else. */
  onWheel?: (e: WheelEvent) => void
}

/** Every flower on the board, and the one open petal card. */
export function FlowerLayer({ boardId, items, view, flowers, locked = false, onWheel }: LayerProps) {
  const world = useLivingWorld()
  const allItems = useItems(boardId).data
  const byId = useMemo(() => new Map((allItems ?? items).map((i) => [i.id, i])), [allItems, items])
  const [open, setOpen] = useState<{ flowerId: string; optionId: string } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const anchorRef = useRef<HTMLDivElement>(null)
  // the open card's spot after clamping: inside the layer and clear of the agent card
  const [placed, setPlaced] = useState<Point | null>(null)

  // a click anywhere else closes the card
  useEffect(() => {
    if (!open) return
    const down = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', down)
    return () => document.removeEventListener('mousedown', down)
  }, [open])

  // TEMPORARY until keep docks the take (Task 7): a free slot beside the petal, clear of the items
  const keepAt = (model: FlowerModel, optionId: string) => (result: Item) => {
    const petal = world.body(`petal:${optionId}`)
    const hub = world.body(model.hubId)
    const near = petal ? { x: petal.x - petal.w / 2, y: petal.y - petal.h / 2, width: petal.w, height: petal.h } : itemBounds(result)
    const dir = petal && hub ? Math.atan2(petal.y - hub.y, petal.x - hub.x) : 0
    const b = placeBeside(near, dir, { width: result.w, height: result.h }, items.map(itemBounds))
    return { x: Math.round(b.x), y: Math.round(b.y) }
  }

  let card = null
  let wanted: Point | null = null
  if (open) {
    const model = flowers.find((f) => f.id === open.flowerId)
    const index = model ? model.options.findIndex((o) => o.id === open.optionId) : -1
    const source = model ? byId.get(model.sourceId) : undefined
    // where the petal is as the card opens (the card does not float with it)
    const petal = world.body(`petal:${open.optionId}`)
    if (model && source && petal && index >= 0 && !model.collapsed) {
      wanted = { x: view.x + (petal.x + petal.w / 2) * view.scale + 8, y: view.y + (petal.y - petal.h / 2) * view.scale }
      const at = placed ?? wanted
      card = (
        <div ref={anchorRef} className="petal-card-anchor" style={{ left: at.x, top: at.y }}>
          <PetalCard
            key={open.optionId}
            option={model.options[index]}
            dimension={{ key: model.key, label: model.label, part: model.part }}
            item={source}
            keepAt={keepAt(model, open.optionId)}
            onClose={() => setOpen(null)}
            locked={locked}
          />
        </div>
      )
    }
  }

  // after every render, and when the card itself grows (a result lands): keep it on screen
  useLayoutEffect(() => {
    const place = () => {
      const el = anchorRef.current
      const layer = rootRef.current?.getBoundingClientRect()
      let next: Point | null = null
      if (wanted && el && layer && layer.width > 0 && layer.height > 0) {
        const card = el.getBoundingClientRect()
        const agent = document.querySelector('.agent-card')?.getBoundingClientRect()
        const avoid = agent && agent.width > 0
          ? { x: agent.left - layer.left, y: agent.top - layer.top, width: agent.width, height: agent.height }
          : null // prettier-ignore
        next = clampCard(wanted, { width: card.width, height: card.height }, layer, avoid)
      }
      setPlaced((old) => (old?.x === next?.x && old?.y === next?.y ? old : next))
    }
    place()
    const el = anchorRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(place)
    ro.observe(el)
    return () => ro.disconnect()
  })

  if (flowers.length === 0) return null
  return (
    <div
      ref={rootRef}
      // an open card sits above the selected item's callouts, which would otherwise cover it
      className={card ? 'flower-layer has-card' : 'flower-layer'}
      onWheel={(e) => {
        if (!(e.target as HTMLElement).closest('.petal-card')) onWheel?.(e)
      }}
    >
      <div className="flower-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        {flowers.map((f) => (
          <Flower
            key={f.id}
            model={f}
            source={byId.get(f.sourceId)}
            byId={byId}
            openOption={open?.flowerId === f.id ? open.optionId : null}
            onOpenOption={(optionId) =>
              setOpen((cur) => (cur?.flowerId === f.id && cur.optionId === optionId ? null : { flowerId: f.id, optionId }))
            }
            onToggle={() => {
              if (!f.collapsed && open?.flowerId === f.id) setOpen(null)
              setCollapsed(boardId, f.id, !f.collapsed)
            }}
          />
        ))}
      </div>
      {card}
    </div>
  )
}
