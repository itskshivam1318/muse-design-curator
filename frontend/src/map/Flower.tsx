/**
 * Exploration flowers over the canvas (HTML in canvas units, like the callouts): a dashed stem from
 * the dimension's callout to a hub, the options around it as petals. A petal opens its card; the hub
 * collapses the flower to a badge on its callout. Only flowers reaching the viewport mount.
 */
import { type WheelEvent, useEffect, useMemo, useRef, useState } from 'react'
import type { ExploreOption, Item, Point } from '../api'
import type { Bounds, View } from '../canvas/geometry'
import { resultCheck } from '../explore/verdict'
import { useItems } from '../queries'
import { setCollapsed } from './collapse'
import { type FlowerLayout, PETAL, PETAL_KEPT, placeBeside } from './layout'
import { PetalCard, ResultPreview } from './PetalCard'
import { isKept, resultOf } from './results'
import type { FlowerModel, MapView } from './useMap'

const centre = (b: Bounds): Point => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 })

type PetalState = 'note' | 'rendered' | 'kept' | 'drifted'

function petalState(option: ExploreOption, result: Item | undefined, label: string): PetalState {
  if (isKept(option)) return 'kept'
  if (!result) return 'note'
  return resultCheck(result.check, label, option.name).tone === 'drift' ? 'drifted' : 'rendered'
}

interface FlowerProps {
  model: FlowerModel
  layout: FlowerLayout
  view: View
  /** The source item (a text result's change is marked against it). */
  source?: Item
  /** Every item, staged results included. */
  byId?: ReadonlyMap<string, Item>
  openOption?: string | null
  onOpenOption?: (optionId: string) => void
  onToggle?: () => void
}

export function Flower({ model, layout, view, source, byId = new Map(), openOption = null, onOpenOption, onToggle }: FlowerProps) {
  const n = model.options.length
  const k = model.options.filter(isKept).length
  const summary = `${n} options · ${k} kept`
  if (model.collapsed) {
    const text = `${model.label} · ${summary}`
    return (
      <div role="group" aria-label={`${model.label} flower`} data-exploration-id={model.id}>
        <button type="button" className="flower-badge" aria-label={text} style={{ left: model.from.x, top: model.from.y }} onClick={onToggle}>
          {text}
        </button>
      </div>
    )
  }
  const [from, hubC] = layout.lines[0]
  return (
    <div role="group" aria-label={`${model.label} flower`} data-exploration-id={model.id}>
      <svg className="flower-lines" width="1" height="1" aria-hidden="true">
        <line className="flower-stem" x1={from.x} y1={from.y} x2={hubC.x} y2={hubC.y} vectorEffect="non-scaling-stroke" />
        {layout.lines.slice(1).map(([p, q], i) => (
          <line key={i} className="flower-spoke" x1={p.x} y1={p.y} x2={q.x} y2={q.y} vectorEffect="non-scaling-stroke" />
        ))}
        <circle className="flower-root" cx={from.x} cy={from.y} r={4 / view.scale} />
      </svg>
      <div className="flower-hub" style={{ left: layout.hub.x, top: layout.hub.y, width: layout.hub.width, height: layout.hub.height }}>
        <span className="flower-hub-label">{model.label}</span>
        <span className="flower-hub-sub">{summary}</span>
        <button type="button" className="flower-collapse" aria-label={`Collapse ${model.label}`} title="Collapse" onClick={onToggle}>
          –
        </button>
      </div>
      {model.options.map((o, i) => {
        const b = layout.petals[i]
        const result = resultOf(o, byId)
        const state = petalState(o, result, model.label)
        const cls = ['petal', `is-${state}`, openOption === o.id && 'is-open'].filter(Boolean).join(' ')
        const showResult = state !== 'note' && result && source
        return (
          <button
            key={o.id}
            type="button"
            className={cls}
            data-testid="petal"
            data-option-id={o.id}
            aria-pressed={openOption === o.id}
            aria-label={`${o.name} · ${o.distance}${state === 'note' ? '' : ` · ${state}`}`}
            style={{ left: b.x, top: b.y, width: b.width, height: b.height }}
            onClick={() => onOpenOption?.(o.id)}
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
      })}
    </div>
  )
}

interface LayerProps {
  boardId: string
  /** The board's items as drawn (not staged): the flowers' sources. */
  items: readonly Item[]
  view: View
  /** The board's map (`useMap`): the visible flowers, every layout, what they kept clear of. */
  map: MapView
  locked?: boolean
  /** Wheel over a flower pans or zooms the canvas like anywhere else. */
  onWheel?: (e: WheelEvent) => void
}

/** Every flower on the board that reaches the viewport, and the one open petal card. */
export function FlowerLayer({ boardId, items, view, map, locked = false, onWheel }: LayerProps) {
  const { flowers, layouts, obstacles } = map
  const allItems = useItems(boardId).data
  const byId = useMemo(() => new Map((allItems ?? items).map((i) => [i.id, i])), [allItems, items])
  const [open, setOpen] = useState<{ flowerId: string; optionId: string } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  // a click anywhere else closes the card
  useEffect(() => {
    if (!open) return
    const down = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', down)
    return () => document.removeEventListener('mousedown', down)
  }, [open])

  /** A free slot beside petal `index` for a result of `size`, clear of items, callouts and every flower. */
  const keepAt = (flowerId: string, index: number) => (result: Item) => {
    const l = layouts.get(flowerId)!
    const petal = l.petals[index]
    const h = centre(l.hub)
    const p = centre(petal)
    // a kept petal grows: leave it the room so no flower has to move
    const grow = PETAL_KEPT - PETAL
    const flowerBoxes = [...layouts.values()].map(({ bounds: b }) => ({
      x: b.x - grow, y: b.y - grow, width: b.width + 2 * grow, height: b.height + 2 * grow,
    }))
    const b = placeBeside(petal, Math.atan2(p.y - h.y, p.x - h.x), { width: result.w, height: result.h }, [...obstacles, ...flowerBoxes])
    return { x: Math.round(b.x), y: Math.round(b.y) }
  }

  let card = null
  if (open) {
    const model = flowers.find((f) => f.id === open.flowerId)
    const index = model ? model.options.findIndex((o) => o.id === open.optionId) : -1
    const source = model ? byId.get(model.itemId) : undefined
    const layout = layouts.get(open.flowerId)
    if (model && source && layout && index >= 0 && !model.collapsed) {
      const petal = layout.petals[index]
      const at = { left: view.x + (petal.x + petal.width) * view.scale + 8, top: view.y + petal.y * view.scale }
      card = (
        <div className="petal-card-anchor" style={at}>
          <PetalCard
            key={open.optionId}
            option={model.options[index]}
            dimension={{ key: model.key, label: model.label, part: model.part }}
            item={source}
            keepAt={keepAt(model.id, index)}
            onClose={() => setOpen(null)}
            locked={locked}
          />
        </div>
      )
    }
  }

  if (flowers.length === 0) return null
  return (
    <div
      ref={rootRef}
      className="flower-layer"
      onWheel={(e) => {
        if (!(e.target as HTMLElement).closest('.petal-card')) onWheel?.(e)
      }}
    >
      <div className="flower-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        {flowers.map((f) => (
          <Flower
            key={f.id}
            model={f}
            layout={layouts.get(f.id)!}
            view={view}
            source={byId.get(f.itemId)}
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
