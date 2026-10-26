import { useId, useState } from 'react'
import type { LensRow, LensSpec } from '../api'
import { humanize } from '../format'
import { groupByKind, KIND_LABEL, partNote } from './lensHelpers'

interface Props {
  lens: LensRow
  /** No spec: confirm the proposal as it is. With a spec: save the edited lens. */
  onConfirm: (spec?: LensSpec) => Promise<unknown>
  onDismiss: () => void
}

/** Review a proposed lens: its parts (with SAM hit-rate notes) and attributes by kind. */
export function LensReview({ lens, onConfirm, onDismiss }: Props) {
  const [editing, setEditing] = useState<LensSpec | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ids = useId()
  const spec = editing ?? lens.spec

  const run = async (edited?: LensSpec) => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(edited)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the lens')
    } finally {
      setBusy(false)
    }
  }

  const removePart = (id: string) =>
    editing &&
    setEditing({
      ...editing,
      parts: editing.parts.filter((p) => p.id !== id),
      attributes: editing.attributes.filter((a) => a.part !== id),
    })
  const removeAttr = (key: string) =>
    editing && setEditing({ ...editing, attributes: editing.attributes.filter((a) => a.key !== key) })
  const renameAttr = (key: string, label: string) =>
    editing &&
    setEditing({ ...editing, attributes: editing.attributes.map((a) => (a.key === key ? { ...a, label } : a)) })

  const labelsOk = !editing || editing.attributes.every((a) => a.label.trim().length > 0)

  return (
    <section className="lens-review" role="dialog" aria-labelledby={`${ids}-h`}>
      <header>
        <p className="eyebrow">Proposed lens · v{lens.version}</p>
        <h2 id={`${ids}-h`}>{spec.label}</h2>
        <p className="muted small">
          What the board will read in every image. Confirm it, or edit it first. Parsing of new items waits for this.
        </p>
      </header>

      <h3 className="eyebrow">Parts</h3>
      {spec.parts.length === 0 && <p className="muted small">Whole image only.</p>}
      <ul className="lens-list">
        {spec.parts.map((p) => {
          const note = partNote(spec, p.id)
          return (
            <li key={p.id}>
              <div>
                <b>{humanize(p.id)}</b>{' '}
                <span className="muted small">
                  {p.grounding === 'sam' ? `located as “${p.sam_prompt}”` : 'whole image'}
                </span>
                {note && <p className="small note">{note}</p>}
              </div>
              {editing && (
                <button type="button" className="btn-quiet small" onClick={() => removePart(p.id)} aria-label={`Remove part ${humanize(p.id)} and its attributes`}>
                  Remove
                </button>
              )}
            </li>
          )
        })}
      </ul>

      {groupByKind(spec.attributes).map(([kind, attrs]) => (
        <div key={kind}>
          <h3 className="eyebrow">{KIND_LABEL[kind] ?? humanize(kind)}</h3>
          <ul className="lens-list">
            {attrs.map((a) => (
              <li key={a.key}>
                {editing ? (
                  <>
                    <label className="sr-only" htmlFor={`${ids}-${a.key}`}>
                      Label for {a.key}
                    </label>
                    <input
                      id={`${ids}-${a.key}`}
                      value={a.label}
                      onChange={(e) => renameAttr(a.key, e.target.value)}
                    />
                    <button type="button" className="btn-quiet small" onClick={() => removeAttr(a.key)} aria-label={`Remove ${a.label || a.key}`}>
                      Remove
                    </button>
                  </>
                ) : (
                  <span>
                    {a.label}
                    {a.part && <span className="muted small"> · {humanize(a.part)}</span>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}

      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      <div className="row-end">
        {editing ? (
          <>
            <button type="button" className="btn-quiet" onClick={() => setEditing(null)} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn" disabled={busy || !labelsOk} onClick={() => void run(editing)}>
              Save lens
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn-quiet" onClick={onDismiss}>
              Later
            </button>
            <button type="button" className="btn-quiet" onClick={() => setEditing(structuredClone(lens.spec))}>
              Edit
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => void run()}>
              Confirm
            </button>
          </>
        )}
      </div>
    </section>
  )
}
