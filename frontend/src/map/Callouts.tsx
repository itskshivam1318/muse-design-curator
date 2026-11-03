/**
 * Part callouts around the selected item (HTML over the canvas, in canvas units like the axes): one
 * card per part with its physical dimensions, Extract and "+ Add dimension"; a dashed "Whole item"
 * card with the abstract dimensions and "+ Add part" (images only). Each card is placed by its body in
 * the living world (`callout:<itemId>:<card>`), ringed around the item. A leader line runs from each
 * part card to an anchor dot on its part. Hovering a card (or focusing one of its buttons) reports the
 * part, so the canvas can highlight its region.
 */
import { useQueryClient } from '@tanstack/react-query'
import { type FocusEvent, type FormEvent, type ReactNode, type WheelEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  addDimension,
  addPart,
  type AnalysisView,
  ApiError,
  type DimensionView,
  extractPart,
  type Item,
  keys,
  type PartView,
  type Point,
} from '../api'
import { formatValue } from '../attrValues'
import type { Bounds, View } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { useBodyElement, useLivingWorld } from '../living/useLiving'
import { writeAttr } from '../living/writeAttr'
import { canAddPart, WHOLE } from './cards'
import { partAnchor, REGION_TAG } from './regions'

const WHOLE_LABEL = 'Whole item'
const STALE_TITLE = 'old dimension, not found on this item'

/** The point of `b` closest to `p` (where a leader line meets its card). */
const nearestOn = (b: Bounds, p: Point): Point => ({
  x: Math.min(b.x + b.width, Math.max(b.x, p.x)),
  y: Math.min(b.y + b.height, Math.max(b.y, p.y)),
})

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError || e instanceof Error ? e.message || fallback : fallback)

interface Props {
  item: Item
  analysis: AnalysisView
  view: View
  /** Clicking a dimension opens its flower (exploring it first if it has none); settles when it is open. */
  onOpenDimension?: (key: string) => unknown
  onHoverPart: (key: string | null) => void
  /**
   * Each card's height as drawn (canvas units; its rows, open forms and error text decide it),
   * reported as it changes, so the card's body matches it.
   */
  onHeights?: (heights: Record<string, number>) => void
  /** Public demo, not unlocked: nothing that changes the item. */
  locked?: boolean
  onWheel?: (e: WheelEvent) => void
}

type Form = { kind: 'dimension'; card: string } | { kind: 'part' } | null

const calloutId = (itemId: string, card: string) => `callout:${itemId}:${card}`

export function Callouts({ item, analysis, view, onOpenDimension, onHoverPart, onHeights, locked = false, onWheel }: Props) {
  const qc = useQueryClient()
  const [form, setForm] = useState<Form>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<{ card: string; text: string } | null>(null)
  // gone (deselected, Escape, a drag or marquee, another item): no part stays highlighted
  const hoverRef = useRef(onHoverPart)
  useLayoutEffect(() => {
    hoverRef.current = onHoverPart
  })
  useEffect(() => () => hoverRef.current(null), [])
  const heightsRef = useRef(onHeights)
  useLayoutEffect(() => {
    heightsRef.current = onHeights
  })
  const heights = useRef(new Map<string, number>())
  const measured = (card: string, h: number) => {
    if (h <= 0 || heights.current.get(card) === h) return
    heights.current.set(card, h)
    heightsRef.current?.(Object.fromEntries(heights.current))
  }
  useEffect(() => () => heightsRef.current?.({}), [])

  const parts = analysis.parts
  const physical = (key: string) => analysis.dimensions.filter((d) => d.type === 'physical' && d.part === key)
  const abstract = analysis.dimensions.filter((d) => d.type === 'abstract')
  const anchors = useMemo(() => new Map(parts.map((p) => [p.key, partAnchor(itemBounds(item), p, item.note_text)])), [item, parts])

  const run = async (card: string, tag: string, fn: () => Promise<unknown>, fallback: string) => {
    setBusy(tag)
    setError(null)
    try {
      await fn()
      return true
    } catch (e) {
      setError({ card, text: errorText(e, fallback) })
      return false
    } finally {
      setBusy(null)
    }
  }
  const refresh = () => qc.invalidateQueries({ queryKey: keys.analysis(item.id) })

  const open = (card: string, d: DimensionView) =>
    onOpenDimension && void run(card, `dim:${d.key}`, async () => onOpenDimension(d.key), 'Could not explore')
  const extract = (p: PartView) =>
    void run(
      p.key,
      `extract:${p.key}`,
      async () => {
        await extractPart(item.id, p.key)
        await qc.invalidateQueries({ queryKey: keys.items(item.board_id) })
      },
      'Could not extract',
    )
  const submitDimension = async (card: string, label: string) => {
    const part = card === WHOLE ? null : card
    const ok = await run(
      card,
      'add',
      async () => {
        await addDimension(item.id, { label, type: part ? 'physical' : 'abstract', part })
        await refresh()
      },
      'Could not add the dimension',
    )
    if (ok) setForm(null)
  }
  const submitPart = async (label: string) => {
    const ok = await run(
      WHOLE,
      'add',
      async () => {
        await addPart(item.id, { label })
        await refresh()
      },
      'Could not add the part',
    )
    if (ok) setForm(null)
  }

  const card = (key: string, title: string, tag: string, dims: DimensionView[], p: PartView | null) => {
    const hoverKey = p ? p.key : null
    return (
      <Card
        key={key}
        id={calloutId(item.id, key)}
        onHeight={(h) => measured(key, h)}
        title={title}
        part={p?.key}
        onMouseEnter={() => onHoverPart(hoverKey)}
        onMouseLeave={() => onHoverPart(null)}
        onFocus={() => onHoverPart(hoverKey)}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onHoverPart(null)
        }}
      >
        <div className="callout-head">
          <span className="callout-title">{title}</span>
          <span className="callout-tag">{tag}</span>
        </div>
        {dims.map((d) => {
          const stale = d.status === 'stale'
          const text = `${d.label} · ${formatValue(d.value)}`
          return (
            <button
              key={d.key}
              type="button"
              className={stale ? 'callout-dim is-stale' : 'callout-dim'}
              title={stale ? STALE_TITLE : text}
              aria-busy={busy === `dim:${d.key}`}
              disabled={locked || !onOpenDimension || busy !== null}
              onClick={() => open(key, d)}
            >
              {d.label} <span className="callout-value">· {formatValue(d.value)}</span>
            </button>
          )
        })}
        {form?.kind === 'dimension' && form.card === key ? (
          <LabelForm name={`New dimension on ${title}`} placeholder="Dimension name" busy={busy === 'add'} onSubmit={(l) => void submitDimension(key, l)} onCancel={() => setForm(null)} />
        ) : null}
        <div className="callout-actions">
          {p && (
            <button type="button" className="callout-act" disabled={locked || busy !== null} aria-busy={busy === `extract:${p.key}`} onClick={() => extract(p)}>
              Extract
            </button>
          )}
          <button type="button" className="callout-act" disabled={locked || busy !== null} onClick={() => setForm({ kind: 'dimension', card: key })}>
            + Add dimension
          </button>
        </div>
        {!p && canAddPart(item, analysis) && (
          <>
            {form?.kind === 'part' && (
              <LabelForm name="New part" placeholder="Part name" busy={busy === 'add'} onSubmit={(l) => void submitPart(l)} onCancel={() => setForm(null)} />
            )}
            <div className="callout-actions">
              <button type="button" className="callout-act" disabled={locked || busy !== null} onClick={() => setForm({ kind: 'part' })}>
                + Add part
              </button>
            </div>
          </>
        )}
        {error?.card === key && (
          <p className="error small" role="alert">
            {error.text}
          </p>
        )}
      </Card>
    )
  }

  return (
    <div className="callout-layer" onWheel={onWheel}>
      <div className="callout-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        <Leaders item={item} anchors={anchors} view={view} />
        {parts.map((p) => card(p.key, p.label, REGION_TAG[p.region_kind], physical(p.key), p))}
        {card(WHOLE, WHOLE_LABEL, 'no mask', abstract, null)}
      </div>
    </div>
  )
}

interface CardProps {
  id: string
  title: string
  /** The part's key; none on the Whole item card. */
  part?: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onFocus: () => void
  onBlur: (e: FocusEvent<HTMLDivElement>) => void
  /** The card's drawn height, after each render and whenever its content resizes it. */
  onHeight: (h: number) => void
  children: ReactNode
}

/** A callout card, placed by its body. */
function Card({ id, title, part, onHeight, children, ...handlers }: CardProps) {
  const ref = useRef<HTMLDivElement>(null)
  // the body takes the card's width; the card keeps the height its content needs, which is measured
  useBodyElement(id, ref, { ownHeight: true })
  const onHeightRef = useRef(onHeight)
  useLayoutEffect(() => {
    onHeightRef.current = onHeight
  })
  useLayoutEffect(() => {
    if (ref.current) onHeightRef.current(ref.current.offsetHeight)
  })
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => onHeightRef.current(el.offsetHeight))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return (
    <div ref={ref} role="group" aria-label={title} className={part ? 'callout' : 'callout is-whole'} data-part={part} {...handlers}>
      {children}
    </div>
  )
}

const r2 = (n: number) => Math.round(n * 100) / 100

/**
 * A leader from each part's anchor (where it sits on the item, carried with the item's body) to the
 * nearest point of its card's body, written every frame.
 */
function Leaders({ item, anchors, view }: { item: Item; anchors: ReadonlyMap<string, Point>; view: View }) {
  const world = useLivingWorld()
  const lines = useRef(new Map<string, SVGLineElement>())
  const dots = useRef(new Map<string, SVGCircleElement>())
  useEffect(() => {
    const home = itemBounds(item)
    const cx = home.x + home.width / 2
    const cy = home.y + home.height / 2
    const write = (): void => {
      const owner = world.body(item.id)
      for (const [key, a] of anchors) {
        const line = lines.current.get(key)
        const dot = dots.current.get(key)
        const card = world.body(calloutId(item.id, key))
        if (!line || !dot || !card) continue
        const at = owner ? { x: owner.x + a.x - cx, y: owner.y + a.y - cy } : a
        const box: Bounds = { x: card.x - card.w / 2, y: card.y - card.h / 2, width: card.w, height: card.h }
        const end = nearestOn(box, at)
        // to 0.01px, and only what changed: a leader at rest costs nothing
        writeAttr(line, 'x1', String(r2(at.x)))
        writeAttr(line, 'y1', String(r2(at.y)))
        writeAttr(line, 'x2', String(r2(end.x)))
        writeAttr(line, 'y2', String(r2(end.y)))
        writeAttr(dot, 'cx', String(r2(at.x)))
        writeAttr(dot, 'cy', String(r2(at.y)))
      }
    }
    write()
    return world.onFrame(write)
  }, [world, item, anchors])
  return (
    <svg className="callout-lines" width="1" height="1" aria-hidden="true">
      {[...anchors.keys()].map((key) => (
        <g key={key}>
          <line
            ref={(el) => {
              if (el) lines.current.set(key, el)
              else lines.current.delete(key)
            }}
            className="callout-leader"
            vectorEffect="non-scaling-stroke"
          />
          <circle
            ref={(el) => {
              if (el) dots.current.set(key, el)
              else dots.current.delete(key)
            }}
            className="callout-anchor"
            r={5 / view.scale}
            strokeWidth={2 / view.scale}
          />
        </g>
      ))}
    </svg>
  )
}

function LabelForm({
  name,
  placeholder,
  busy,
  onSubmit,
  onCancel,
}: {
  name: string
  placeholder: string
  busy: boolean
  onSubmit: (label: string) => void
  onCancel: () => void
}) {
  const [text, setText] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const label = text.trim()
    if (label) onSubmit(label)
  }
  return (
    <form className="callout-form" onSubmit={submit}>
      <input
        type="text"
        aria-label={name}
        placeholder={placeholder}
        value={text}
        disabled={busy}
        autoFocus
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== 'Escape') return
          e.stopPropagation()
          onCancel()
        }}
      />
    </form>
  )
}
