import { useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { keys, unlockDemo } from '../api'
import { useDemo } from '../demo'
import { useDialog } from '../ui/useDialog'

/** In demo mode: a "Demo — read-only" chip with an Unlock button (passcode dialog). */
export function DemoBadge() {
  const { demoMode, locked } = useDemo()
  const [open, setOpen] = useState(false)
  if (!demoMode) return null
  return (
    <span className="demo-badge">
      <span className={locked ? 'chip is-demo' : 'chip'}>{locked ? 'Demo — read-only' : 'Demo — unlocked'}</span>
      {locked && (
        <button type="button" className="btn-quiet small" onClick={() => setOpen(true)}>
          Unlock
        </button>
      )}
      {open && <UnlockDialog onClose={() => setOpen(false)} />}
    </span>
  )
}

export function UnlockDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const dialog = useDialog<HTMLFormElement>(onClose)
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const id = useId()

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      qc.setQueryData(keys.demo, await unlockDemo(passcode))
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not unlock')
      setBusy(false)
    }
  }

  return (
    <form
      className="unlock-dialog"
      aria-labelledby={`${id}-h`}
      {...dialog}
      onSubmit={(e) => {
        e.preventDefault()
        if (passcode) void submit()
      }}
    >
      <h2 id={`${id}-h`}>Unlock the demo</h2>
      <p className="small muted">The passcode lets you add references and edit. Every upload and Vary uses the paid model API.</p>
      <label htmlFor={`${id}-p`}>Passcode</label>
      <input
        id={`${id}-p`}
        type="password"
        autoComplete="current-password"
        data-autofocus
        value={passcode}
        onChange={(e) => setPasscode(e.target.value)}
        aria-invalid={error ? true : undefined}
      />
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      <div className="row-end">
        <button type="button" className="btn-quiet" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn" disabled={!passcode || busy}>
          {busy ? 'Unlocking…' : 'Unlock'}
        </button>
      </div>
    </form>
  )
}
