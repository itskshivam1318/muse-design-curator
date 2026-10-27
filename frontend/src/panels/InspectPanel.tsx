import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  type AttributeSpec,
  type AttrValue,
  getAttributeHistory,
  type ItemAttribute,
  type ItemAttributes,
  keys,
  patchAttribute,
} from '../api'
import { CreditLine } from '../canvas/CreditCaption'
import { selection } from '../canvas/selection'
import { humanize, itemTitle } from '../format'
import { itemVerdict } from '../explore/verdict'
import { useAttributes, useExplorations, useItems, useProfile } from '../queries'
import { COLOR_TABLE, colorHex, formatValue, isBoardSignal, numberBounds, scaleOf, vocabularyOf } from '../vary/logic'
import { Swatch } from './AttrBits'
import type { DrawerPanelProps } from './drawerRegistry'
import { PanelHead } from './PanelHead'

const TEXT_DEBOUNCE_MS = 600

const STATUS_CHIP: Partial<Record<ItemAttribute['status'], string>> = {
  edited: 'edited by you',
  confirmed: 'confirmed',
  uncertain: 'uncertain',
  missing: 'unknown',
}

type Patch = { value: AttrValue } | { action: 'confirm' | 'disable' | 'enable' }

function usePatch(itemId: string) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const send = async (key: string, body: Patch) => {
    setError(null)
    try {
      const row = await patchAttribute(itemId, key, body)
      qc.setQueryData<ItemAttributes>(keys.attributes(itemId), (old) =>
        old
          ? {
              ...old,
              attributes: old.attributes.some((a) => a.key === key)
                ? old.attributes.map((a) => (a.key === key ? { ...a, ...row } : a))
                : [...old.attributes, row],
            }
          : old,
      )
      void qc.invalidateQueries({ queryKey: keys.attributeHistory(itemId, key) })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save')
    }
  }
  return { send, error }
}

/** A lens attribute with no record yet (never read): edits create it. */
function blank(spec: AttributeSpec): ItemAttribute {
  return {
    key: spec.key, label: spec.label, category: spec.category, kind: spec.kind as ItemAttribute['kind'],
    part: (spec.part as string | null) ?? null, value: null, confidence: 0, status: 'missing', source: 'user',
    enabled: true,
  }
}

/** Every attribute of one item, grouped by category, each with an editor for its kind. */
export function InspectPanel({ boardId, itemId, onClose, locked = false }: DrawerPanelProps) {
  const q = useAttributes(itemId)
  const item = useItems(boardId).data?.find((i) => i.id === itemId)
  const profile = useProfile(boardId).data?.profile
  const { send, error } = usePatch(itemId)
  const lens = q.data?.lens
  const explorations = useExplorations(boardId).data
  const verdict = useMemo(
    () => (item ? itemVerdict(item, explorations, new Map((lens?.attributes ?? []).map((a) => [a.key, a.label]))) : null),
    [item, explorations, lens],
  )

  const groups = useMemo(() => {
    const recs = new Map((q.data?.attributes ?? []).map((a) => [a.key, a]))
    const specs = lens?.attributes ?? []
    const out = new Map<string, { spec: AttributeSpec; rec: ItemAttribute }[]>()
    for (const spec of specs) {
      const list = out.get(spec.category) ?? []
      list.push({ spec, rec: recs.get(spec.key) ?? blank(spec) })
      out.set(spec.category, list)
    }
    return [...out]
  }, [q.data, lens])

  return (
    <div className="panel inspect-panel">
      <PanelHead
        eyebrow="Inspect"
        title={item ? itemTitle(item) : 'Item'}
        onClose={onClose}
        sub={item?.licence && !item.generation && <CreditLine licence={item.licence} className="credit panel-credit small muted" />}
      />
      <div className="panel-body">
        {item?.generation && verdict && (
          <section className="attr-group generated-from">
            <h3 className="eyebrow">{verdict.optionName ? `Generated from ${verdict.optionName}` : 'Generated image'}</h3>
            <p className={`verdict verdict-${verdict.tone}`}>{verdict.text}</p>
            <p className="small muted">Model: {item.generation.model}</p>
            <p className="small muted">Prompt: {item.generation.prompt}</p>
          </section>
        )}
        {q.isPending && <p className="muted">Loading attributes…</p>}
        {q.isError && <p className="error">Could not load attributes: {q.error.message}</p>}
        {q.data && q.data.parse_status !== 'completed' && (
          <p className="note small">
            {q.data.parse_status === 'failed'
              ? `Parsing failed${q.data.parse_error_code ? ` (${q.data.parse_error_code})` : ''}.`
              : 'Still reading this item; values will fill in.'}
          </p>
        )}
        {q.data?.provider.is_mock && (
          <p className="small muted">Values were read by the mock provider, not a real model.</p>
        )}
        {q.isSuccess && !lens && <p className="muted">This board has no confirmed lens yet.</p>}
        {locked && <p className="note small">Demo — read-only: unlock to edit values.</p>}
        {error && (
          <p className="error small" role="alert">
            {error}
          </p>
        )}
        {groups.map(([category, rows]) => (
          <section key={category} className="attr-group">
            <h3 className="eyebrow">{humanize(category)}</h3>
            <ul className="attr-rows">
              {rows.map(({ spec, rec }) => (
                <AttributeRow
                  key={spec.key}
                  itemId={itemId}
                  spec={spec}
                  rec={rec}
                  signal={isBoardSignal(spec.key, profile)}
                  locked={locked}
                  onPatch={(body) => void send(spec.key, body)}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}

function AttributeRow({
  itemId,
  spec,
  rec,
  signal,
  onPatch,
  locked = false,
}: {
  itemId: string
  spec: AttributeSpec
  rec: ItemAttribute
  signal: boolean
  onPatch: (body: Patch) => void
  locked?: boolean
}) {
  const chip = STATUS_CHIP[rec.status]
  const labelId = `attr-${spec.key}`
  return (
    <li className={rec.enabled ? 'attr-row' : 'attr-row is-disabled'} role="group" aria-labelledby={labelId}>
      <div className="attr-head">
        <span id={labelId} className="attr-label">
          {spec.label}
        </span>
        {signal && <span className="mark is-signal">board signal</span>}
        {chip && <span className={`mark is-${rec.status}`}>{chip}</span>}
        <label className="switch" title={rec.enabled ? 'Used by signals and Vary' : 'Ignored'}>
          <input
            type="checkbox"
            role="switch"
            aria-label={`Use ${spec.label}`}
            checked={rec.enabled}
            disabled={locked}
            onChange={(e) => onPatch({ action: e.target.checked ? 'enable' : 'disable' })}
          />
        </label>
      </div>
      <fieldset className="plain-fieldset" disabled={locked}>
        <Editor spec={spec} rec={rec} onValue={(value) => value !== rec.value && onPatch({ value })} />
      </fieldset>
      <div className="attr-actions">
        {rec.value !== null && rec.status !== 'confirmed' && rec.status !== 'edited' && (
          <button type="button" className="btn-quiet small" aria-label={`Confirm ${spec.label}`} disabled={locked} onClick={() => onPatch({ action: 'confirm' })}>
            Confirm
          </button>
        )}
        <button
          type="button"
          className="btn-quiet small"
          aria-label={`Vary ${spec.label}`}
          disabled={!rec.enabled}
          onClick={() => selection.openDrawer('vary', itemId, { targetKey: spec.key })}
        >
          Vary this
        </button>
        <History itemId={itemId} attrKey={spec.key} />
      </div>
    </li>
  )
}

function Editor({ spec, rec, onValue }: { spec: AttributeSpec; rec: ItemAttribute; onValue: (v: AttrValue) => void }) {
  const name = `${spec.label} value`
  const v = rec.value
  switch (spec.kind) {
    case 'enum': {
      const vocab = vocabularyOf(spec)
      const opts = typeof v === 'string' && !vocab.includes(v) ? [v, ...vocab] : vocab
      if (opts.length === 0) return <TextEditor name={name} value={typeof v === 'string' ? v : ''} onCommit={onValue} />
      return (
        <select aria-label={name} value={typeof v === 'string' ? v : ''} onChange={(e) => onValue(e.target.value || null)}>
          <option value="">Unknown</option>
          {opts.map((o) => (
            <option key={o} value={o}>
              {formatValue(o)}
            </option>
          ))}
        </select>
      )
    }
    case 'ordinal':
      return (
        <div role="radiogroup" aria-label={name} className="seg small">
          {scaleOf(spec).map((s) => (
            <button key={s} type="button" role="radio" aria-checked={v === s} aria-label={s} onClick={() => onValue(s)}>
              {formatValue(s)}
            </button>
          ))}
        </div>
      )
    case 'number':
      return <NumberEditor spec={spec} value={typeof v === 'number' ? v : null} onValue={onValue} />
    case 'boolean':
      return (
        <label className="toggle">
          <input type="checkbox" role="switch" aria-label={name} checked={v === true} onChange={(e) => onValue(e.target.checked)} />
          <span>{v === null ? 'Unknown' : v ? 'Yes' : 'No'}</span>
        </label>
      )
    case 'color': {
      const hex = colorHex(v, rec.measured)
      return (
        <div className="color-editor">
          <Swatch hex={hex} />
          <code className="small">{hex ?? '—'}</code>
          <select aria-label={name} value={typeof v === 'string' ? v : ''} onChange={(e) => onValue(e.target.value || null)}>
            <option value="">Unknown</option>
            {Object.keys(COLOR_TABLE).map((c) => (
              <option key={c} value={c}>
                {formatValue(c)}
              </option>
            ))}
          </select>
        </div>
      )
    }
    case 'shape':
      return <ShapeThumb measured={rec.measured} />
    default:
      return <TextEditor name={name} value={typeof v === 'string' ? v : ''} onCommit={onValue} />
  }
}

function NumberEditor({ spec, value, onValue }: { spec: AttributeSpec; value: number | null; onValue: (v: number) => void }) {
  const b = numberBounds(spec)!
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  const [shown, setShown] = useState(value)
  if (shown !== value) {
    // the saved value changed (our edit or the server's): show it
    setShown(value)
    setDraft(value === null ? '' : String(value))
  }
  const clamp = (n: number) => Math.min(b.max, Math.max(b.min, Math.round(n * 1000) / 1000))
  const step = (dir: 1 | -1) => onValue(clamp((value ?? (b.min + b.max) / 2) + dir * b.tolerance))
  const commit = () => {
    const n = Number(draft)
    if (draft.trim() !== '' && Number.isFinite(n) && n !== value) onValue(clamp(n))
  }
  return (
    <div className="stepper">
      <button type="button" className="icon-btn" aria-label={`Decrease ${spec.label}`} onClick={() => step(-1)} disabled={value !== null && value <= b.min}>
        −
      </button>
      <input
        type="number"
        aria-label={`${spec.label} value`}
        value={draft}
        min={b.min}
        max={b.max}
        step={b.tolerance}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      <span className="muted small">{b.unit}</span>
      <button type="button" className="icon-btn" aria-label={`Increase ${spec.label}`} onClick={() => step(1)} disabled={value !== null && value >= b.max}>
        +
      </button>
    </div>
  )
}

/** Free text, saved after a pause in typing (and on blur). */
export function TextEditor({ name, value, onCommit }: { name: string; value: string; onCommit: (v: string | null) => void }) {
  const [draft, setDraft] = useState(value)
  const [shown, setShown] = useState(value)
  const saved = useRef(value)
  const commitRef = useRef(onCommit)
  const draftRef = useRef(draft)
  useEffect(() => {
    commitRef.current = onCommit
    draftRef.current = draft
  })
  // leaving with an unsaved edit (drawer closed, item switched) saves it instead of dropping it
  useEffect(
    () => () => {
      if (draftRef.current === saved.current) return
      saved.current = draftRef.current
      commitRef.current(draftRef.current.trim() || null)
    },
    [],
  )
  useEffect(() => {
    saved.current = value
  }, [value])
  if (shown !== value) {
    setShown(value)
    setDraft(value)
  }
  useEffect(() => {
    if (draft === saved.current) return
    const t = setTimeout(() => {
      saved.current = draft
      commitRef.current(draft.trim() || null)
    }, TEXT_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [draft])
  const flush = () => {
    if (draft === saved.current) return
    saved.current = draft
    onCommit(draft.trim() || null)
  }
  return <input type="text" aria-label={name} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={flush} />
}

function ShapeThumb({ measured }: { measured?: Record<string, unknown> | null }) {
  const pts = Array.isArray(measured?.contour) ? (measured.contour as number[][]) : []
  if (pts.length < 3) return <p className="muted small">No outline measured.</p>
  const d = pts.map(([x, y]) => `${x.toFixed(3)},${y.toFixed(3)}`).join(' ')
  return (
    <svg className="shape-thumb" viewBox="-2.4 -2.4 4.8 4.8" role="img" aria-label="Measured outline">
      <polygon points={d} fill="none" stroke="currentColor" strokeWidth="0.06" />
    </svg>
  )
}

function History({ itemId, attrKey }: { itemId: string; attrKey: string }) {
  const [open, setOpen] = useState(false)
  const q = useQuery({
    queryKey: keys.attributeHistory(itemId, attrKey),
    queryFn: () => getAttributeHistory(itemId, attrKey),
    enabled: open,
  })
  const show = (s: Record<string, unknown> | null) => (s && 'value' in s ? formatValue(s.value as AttrValue) : '—')
  return (
    <details className="history" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>History</summary>
      {q.isPending && open && <p className="muted small">Loading…</p>}
      {q.data && q.data.length === 0 && <p className="muted small">No changes yet.</p>}
      {q.data && q.data.length > 0 && (
        <ul>
          {q.data.map((e) => (
            <li key={e.id} className="small">
              {humanize(e.action)} by {e.actor}: {show(e.before)} → {show(e.after)}
              <span className="muted"> · {new Date(e.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}
