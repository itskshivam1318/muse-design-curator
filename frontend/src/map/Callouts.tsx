/**
 * Part callouts around the selected item (HTML over the canvas, in canvas units like the axes): one
 * card per part with its physical dimensions, Extract and "+ Add dimension"; a dashed "Whole item"
 * card with the abstract dimensions and "+ Add part". A leader line runs from each part card to an
 * anchor dot on its part. Hovering a card (or focusing one of its buttons) reports the part, so the
 * canvas can highlight its region.
 */
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type WheelEvent, useState } from 'react'
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
import { calloutSlots } from './layout'
import { partAnchor, REGION_TAG } from './regions'

/** The Whole item card's key among the part keys (part keys are slugs: no colon). */
const WHOLE = 'whole:item'
const WHOLE_LABEL = 'Whole item'
const STALE_TITLE = 'old dimension, not found on this item'


// card geometry (canvas units), mirrored by the .callout CSS
const PAD = 8
const HEAD_H = 24
const ROW_H = 30
const ROW_GAP = 4
const FORM_H = 34

/** The card's height for its rows: header, one row per dimension, the action row, open forms. */
const cardHeight = (rows: number, actionRows: number, forms: number) =>
  PAD * 2 + HEAD_H + (rows + actionRows) * (ROW_H + ROW_GAP) + forms * FORM_H

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
  /** Clicking a dimension explores it; the promise settles when the options are there. */
  onOpenDimension?: (key: string) => unknown
  onHoverPart: (key: string | null) => void
  /** Other things on the board the cards keep clear of. */
  obstacles?: Bounds[]
  /** Public demo, not unlocked: nothing that changes the item. */
  locked?: boolean
  onWheel?: (e: WheelEvent) => void
}

type Form = { kind: 'dimension'; card: string } | { kind: 'part' } | null

export function Callouts({ item, analysis, view, onOpenDimension, onHoverPart, obstacles = [], locked = false, onWheel }: Props) {
  const qc = useQueryClient()
  const [form, setForm] = useState<Form>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<{ card: string; text: string } | null>(null)

  const bounds = itemBounds(item)
  const parts = analysis.parts
  const physical = (key: string) => analysis.dimensions.filter((d) => d.type === 'physical' && d.part === key)
  const abstract = analysis.dimensions.filter((d) => d.type === 'abstract')
  const formsOn = (card: string) =>
    (form?.kind === 'dimension' && form.card === card ? 1 : 0) + (card === WHOLE && form?.kind === 'part' ? 1 : 0)
  const anchors = new Map(parts.map((p) => [p.key, partAnchor(bounds, p, item.note_text)]))
  const slots = calloutSlots(
    bounds,
    [
      ...parts.map((p) => ({ key: p.key, anchor: anchors.get(p.key)!, height: cardHeight(physical(p.key).length, 1, formsOn(p.key)) })),
      {
        key: WHOLE,
        anchor: { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height },
        height: cardHeight(abstract.length, 2, formsOn(WHOLE)),
      },
    ],
    obstacles,
  )

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
    const slot = slots.get(key)
    if (!slot) return null
    const hoverKey = p ? p.key : null
    return (
      <div
        key={key}
        role="group"
        aria-label={title}
        className={p ? 'callout' : 'callout is-whole'}
        data-part={p?.key}
        style={{ left: slot.x, top: slot.y, width: slot.width, minHeight: slot.height }}
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
          return (
            <button
              key={d.key}
              type="button"
              className={stale ? 'callout-dim is-stale' : 'callout-dim'}
              title={stale ? STALE_TITLE : undefined}
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
        {!p && (
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
      </div>
    )
  }

  const dot = 5 / view.scale
  return (
    <div className="callout-layer" onWheel={onWheel}>
      <div className="callout-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
        <svg className="callout-lines" width="1" height="1" aria-hidden="true">
          {parts.map((p) => {
            const slot = slots.get(p.key)
            const a = anchors.get(p.key)!
            if (!slot) return null
            const end = nearestOn(slot, a)
            return (
              <g key={p.key}>
                <line className="callout-leader" x1={a.x} y1={a.y} x2={end.x} y2={end.y} vectorEffect="non-scaling-stroke" />
                <circle className="callout-anchor" cx={a.x} cy={a.y} r={dot} strokeWidth={2 / view.scale} />
              </g>
            )
          })}
        </svg>
        {parts.map((p) => card(p.key, p.label, REGION_TAG[p.region_kind], physical(p.key), p))}
        {card(WHOLE, WHOLE_LABEL, 'no mask', abstract, null)}
      </div>
    </div>
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
