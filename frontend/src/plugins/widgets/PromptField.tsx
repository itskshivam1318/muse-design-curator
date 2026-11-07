/** A multi-line prompt; Describe fills it from what the node's inputs show. */
import { useState } from 'react'
import { ApiError, describeNode } from '../../api'

interface Props {
  id: string
  nodeId: string
  value: unknown
  describe?: boolean
  readOnly?: boolean
  onSave: (v: unknown) => void
}

export function PromptField({ id, nodeId, value, describe, readOnly, onSave }: Props) {
  const initial = typeof value === 'string' ? value : ''
  const [draft, setDraft] = useState(initial)
  const [shownFor, setShownFor] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (shownFor !== initial) {
    setShownFor(initial)
    setDraft(initial)
  }
  const commit = () => draft !== initial && onSave(draft)
  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      const { prompt } = await describeNode(nodeId)
      setDraft(prompt)
      onSave(prompt)
    } catch (e) {
      const shown = e instanceof ApiError && (e.code === 'DAILY_LIMIT' || e.code === 'DEMO_LOCKED')
      setErr(shown ? e.message : 'Could not describe the inputs')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="node-prompt">
      <textarea id={id} rows={4} value={draft} disabled={readOnly} onChange={(e) => setDraft(e.target.value)} onBlur={commit} />
      {describe && (
        <button type="button" className="node-mini" disabled={readOnly || busy} onClick={() => void run()}>
          {busy ? 'Describing…' : 'Describe'}
        </button>
      )}
      {err && <span className="node-field-bad" role="alert">{err}</span>}
    </div>
  )
}
