import { useEffect, useMemo, useRef, useState } from 'react'
import type { LensRow } from '../api'
import { countedItems, useBoardLens, useItems, useProfile } from '../queries'
import { ProgressDots, UNLOCK_AT } from './Onboarding'
import { type Row, signalRows } from './signalRows'

const rowText = (r: Row) => `${r.value}|${r.count ?? ''}|${(r.swatches ?? []).join(',')}`

function useChangedRows(rows: Row[]): Set<string> {
  const prev = useRef<Map<string, string> | null>(null)
  const [changed, setChanged] = useState<Set<string>>(new Set())
  useEffect(() => {
    const now = new Map(rows.map((r) => [r.id, rowText(r)]))
    const before = prev.current
    prev.current = now
    if (!before) return
    const diff = new Set([...now].filter(([id, text]) => before.get(id) !== text).map(([id]) => id))
    if (diff.size === 0) return
    setChanged(diff)
    const t = setTimeout(() => setChanged(new Set()), 1600)
    return () => clearTimeout(t)
  }, [rows])
  return changed
}

function LensChip({ lens }: { lens: LensRow | null | undefined }) {
  if (!lens) return <span className="chip is-quiet">No lens yet</span>
  const status = lens.status === 'proposed' ? 'proposed, awaiting review' : lens.spec.origin
  return (
    <span className="chip" title={`${lens.spec.label} lens, v${lens.version}`}>
      {lens.spec.label} lens · {status}
    </span>
  )
}

/** Board intelligence on the right edge; updates live as profile.updated events arrive. */
export function BoardSignals({ boardId }: { boardId: string }) {
  const profile = useProfile(boardId).data?.profile
  const items = countedItems(useItems(boardId).data ?? [])
  const lens = useBoardLens(boardId).data
  const [open, setOpen] = useState(true)
  const rows = useMemo(() => (profile ? signalRows(profile) : []), [profile])
  const changed = useChangedRows(rows)
  const refs = items.filter((i) => i.role === 'reference').length
  const groups: [Row['group'], string][] = [
    ['signal', 'Signals'],
    ['tension', 'Tensions'],
    ['counter', 'Not this'],
  ]

  return (
    <aside className={open ? 'signals' : 'signals is-collapsed'} aria-label="Board signals">
      <header className="signals-head">
        <span className="eyebrow">
          Board · {items.length} {items.length === 1 ? 'item' : 'items'}
        </span>
        <button
          type="button"
          className="icon-btn"
          aria-expanded={open}
          aria-controls="signals-body"
          aria-label={open ? 'Collapse board signals' : 'Expand board signals'}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? '–' : '+'}
        </button>
      </header>
      {open && (
        <div id="signals-body" className="signals-body" aria-live="polite">
          <LensChip lens={lens} />
          {refs < UNLOCK_AT && (
            <div className="unlock">
              <span>Add {UNLOCK_AT} to unlock board intelligence</span>
              <ProgressDots count={refs} of={UNLOCK_AT} />
            </div>
          )}
          {rows.length === 0 && refs >= UNLOCK_AT && (
            <p className="muted small">No consistent signals yet.</p>
          )}
          {groups.map(([g, title]) => {
            const list = rows.filter((r) => r.group === g)
            if (list.length === 0) return null
            return (
              <section key={g} className={`sig-group is-${g}`}>
                <h3 className="eyebrow">{title}</h3>
                <ul>
                  {list.map((r) => (
                    <li key={r.id} className="sig" data-changed={changed.has(r.id) ? 'true' : undefined}>
                      {g === 'tension' ? (
                        <span>{r.value}</span>
                      ) : (
                        <span className="sig-text">
                          {r.swatches?.map((hex) => (
                            <i key={hex} className="swatch" style={{ background: hex }} aria-hidden="true" />
                          ))}
                          <span className="sig-label">{r.label}</span>
                          <span className="sig-value">{r.value}</span>
                        </span>
                      )}
                      {r.count && <b>{r.count}</b>}
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      )}
    </aside>
  )
}
