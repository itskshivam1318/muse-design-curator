import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  type AttributeSpec,
  type CandidateCheck,
  type CandidateView,
  corpusImageUrl,
  type DecisionBody,
  type Item,
  keys,
  postDecision,
} from '../api'
import { upsertItems } from '../events'
import { safeExternalUrl } from '../format'
import { useAttributes } from '../queries'
import { colorHex, formatValue, NOTE_MAX, numberBounds, originLabel, REJECT_REASON_LABELS, scaleOf, verdictMark } from '../vary/logic'
import { idempotencyKey } from '../vary/startRun'
import { useDialog } from '../ui/useDialog'
import { ScaleView, Swatch, ValueText } from './AttrBits'

interface Props {
  boardId: string
  runId: string
  candidate: CandidateView
  sourceItemId: string
  targetKey: string
  onClose: () => void
  /** Called with the new board item and the popover image's screen rect (for the fly-in). */
  onKept?: (item: Item, from: DOMRect | null) => void
}

const CHECK_TITLE: Record<string, string> = { provenance: 'Licence', duplicate: 'Duplicate' }

/** Click a strip thumbnail: the candidate large, its credit, the target change and every check. */
export function CandidatePopover({ boardId, runId, candidate: c, sourceItemId, targetKey, onClose, onKept }: Props) {
  const qc = useQueryClient()
  const source = useAttributes(sourceItemId).data
  const specs = new Map((source?.lens?.attributes ?? []).map((a) => [a.key, a]))
  const srcRec = source?.attributes.find((a) => a.key === targetKey)
  const tspec = specs.get(targetKey)
  const img = useRef<HTMLImageElement>(null)
  const dialog = useDialog<HTMLDivElement>(onClose)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [notThis, setNotThis] = useState(false)
  const [busy, setBusy] = useState(false)
  const firstReason = useRef<HTMLButtonElement>(null)
  const rejectBtn = useRef<HTMLButtonElement>(null)
  const wasRejecting = useRef(false)
  // entering the reject form focuses its first reason; Cancel returns focus to Reject
  useEffect(() => {
    if (rejecting) firstReason.current?.focus()
    else if (wasRejecting.current) rejectBtn.current?.focus()
    wasRejecting.current = rejecting
  }, [rejecting])
  const [error, setError] = useState<string | null>(null)

  const decide = async (body: DecisionBody) => {
    setBusy(true)
    setError(null)
    try {
      const res = await postDecision(runId, c.id, body, idempotencyKey())
      if (res.item) upsertItems(qc, boardId, [res.item])
      void qc.invalidateQueries({ queryKey: keys.run(runId) })
      if (body.decision === 'keep' && res.item) onKept?.(res.item, img.current?.getBoundingClientRect() ?? null)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the decision')
    } finally {
      setBusy(false)
    }
  }

  const reject = () =>
    decide({
      decision: 'reject',
      ...(reason ? { reason_code: reason } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
      mark_not_this: notThis,
    })

  const p = c.provenance
  const sourceUrl = safeExternalUrl(p.landing_url)
  const unit = numberBounds(tspec)?.unit
  const last = c.decision

  return (
    <div className="cand-pop" aria-label="Candidate" {...dialog}>
      <button type="button" className="icon-btn cand-close" aria-label="Close candidate" onClick={onClose}>
        ×
      </button>
      <img ref={img} className="cand-image" src={corpusImageUrl(c.corpus_item_id)} alt="Candidate image" />
      <p className="credit small muted">
        {[p.credit || p.creator_name, p.license_code].filter(Boolean).join(' · ')}
        {sourceUrl && (
          <>
            {' · '}
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
              Source ↗
            </a>
          </>
        )}
      </p>

      <p className="origin small muted" data-origin={c.origin}>
        {originLabel(c)}
      </p>

      <p className="target-change">
        <span className="muted">{tspec?.label ?? formatValue(targetKey)}</span>{' '}
        {tspec?.kind === 'color' && <Swatch hex={colorHex(srcRec?.value ?? null, srcRec?.measured)} />}
        {tspec?.kind === 'color' && <Swatch hex={colorHex(c.observed_target_value)} />}
        <b>{`${formatValue(srcRec?.value ?? null, unit)} → ${formatValue(c.observed_target_value, unit)}`}</b>
      </p>

      <ul className="checks" aria-label="Checks">
        {c.checks.map((ck, i) => (
          <li key={`${ck.check}:${ck.attribute_key ?? i}`} className={`check is-${ck.verdict}`}>
            <span className="verdict" aria-label={ck.verdict}>
              {verdictMark(ck.verdict)}
            </span>
            <span className="check-body">
              <span className="check-head">
                {ck.attribute_key ? (specs.get(ck.attribute_key)?.label ?? formatValue(ck.attribute_key)) : (CHECK_TITLE[ck.check] ?? formatValue(ck.check))}
                {ck.check === 'protected' && <span className="muted"> · protected</span>}
                <CheckVisual check={ck} spec={ck.attribute_key ? specs.get(ck.attribute_key) : undefined} />
              </span>
              <span className="check-reason">{ck.reason}</span>
            </span>
          </li>
        ))}
        {c.checks.length === 0 && <li className="muted small">No checks recorded.</li>}
      </ul>

      {last && (
        <p className="small muted">
          {last.decision === 'keep' ? 'You kept this.' : `You rejected this${last.reason_code ? `: ${REJECT_REASON_LABELS[last.reason_code] ?? last.reason_code}` : ''}.`}
        </p>
      )}

      {!rejecting ? (
        <div className="row-end">
          <button type="button" ref={rejectBtn} className="btn-quiet" onClick={() => setRejecting(true)} disabled={busy}>
            Reject
          </button>
          <button type="button" className="btn" data-autofocus onClick={() => void decide({ decision: 'keep' })} disabled={busy}>
            Keep
          </button>
        </div>
      ) : (
        <div className="reject-form">
          <div role="radiogroup" aria-label="Reason" className="value-chips">
            {Object.entries(REJECT_REASON_LABELS).map(([code, label], i) => (
              <button
                key={code}
                ref={i === 0 ? firstReason : undefined}
                type="button"
                role="radio"
                aria-checked={reason === code}
                className="vchip"
                onClick={() => setReason(reason === code ? null : code)}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="note-field">
            <span className="small muted">
              Note (optional) · {note.length}/{NOTE_MAX}
            </span>
            <textarea rows={2} maxLength={NOTE_MAX} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={notThis} onChange={(e) => setNotThis(e.target.checked)} />
            Mark as not this
          </label>
          <p className="small muted">"Not this" adds it to the board as a counter-example.</p>
          <div className="row-end">
            <button type="button" className="btn-quiet" onClick={() => setRejecting(false)} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn" onClick={() => void reject()} disabled={busy}>
              Confirm reject
            </button>
          </div>
        </div>
      )}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}

      {c.decisions.length > 0 && (
        <details className="history">
          <summary>Decision history ({c.decisions.length})</summary>
          <ul>
            {c.decisions.map((d) => (
              <li key={d.id} className="small">
                {d.decision === 'keep' ? 'Kept' : 'Rejected'}
                {d.reason_code ? ` · ${REJECT_REASON_LABELS[d.reason_code] ?? d.reason_code}` : ''}
                {d.note ? ` · “${d.note}”` : ''}
                <span className="muted"> · {new Date(d.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

/** colour: two swatches; ordinal: a mini scale; shape: the similarity number. */
function CheckVisual({ check, spec }: { check: CandidateCheck; spec?: AttributeSpec }) {
  const vals = check.evidence?.values ?? {}
  if (spec?.kind === 'color') {
    const hexes = check.reason.match(/#[0-9a-f]{6}/gi) ?? []
    const a = hexes[0] ?? colorHex(vals.source as string)
    const b = hexes[1] ?? colorHex(vals.candidate as string)
    if (!a && !b) return null
    return (
      <span className="check-visual">
        <Swatch hex={a ?? null} label="reference" />
        <Swatch hex={b ?? null} label="candidate" />
      </span>
    )
  }
  if (spec?.kind === 'ordinal') {
    return (
      <span className="check-visual">
        <ScaleView className="mini-scale" scale={scaleOf(spec)} current={vals.source as string} target={vals.candidate as string} />
      </span>
    )
  }
  if (spec?.kind === 'shape' && typeof vals.similarity === 'number') {
    return <span className="check-visual mono">sim {vals.similarity.toFixed(2)}</span>
  }
  if (spec?.kind === 'number' && vals.candidate !== undefined) {
    return (
      <span className="check-visual">
        <ValueText kind="number" value={vals.candidate as number} unit={numberBounds(spec)?.unit} />
      </span>
    )
  }
  return null
}
