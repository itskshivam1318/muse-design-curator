/** A whole-number seed with a Shuffle button that sets a new random one. */
import { useState } from 'react'

const MAX_SEED = 2147483647

/** A random whole number in [min, max] that is not `current`. */
function newSeed(current: unknown, min = 0, max = MAX_SEED): number {
  const lo = Math.max(min, 0)
  const hi = Math.min(max, MAX_SEED)
  if (hi <= lo) return lo
  let n = current
  while (n === current) n = lo + Math.floor(Math.random() * (hi - lo + 1))
  return n as number
}

interface Props {
  id: string
  value: unknown
  min?: number
  max?: number
  readOnly?: boolean
  onSave: (v: unknown) => void
}

export function SeedButton({ id, value, min, max, readOnly, onSave }: Props) {
  const initial = value === undefined || value === null ? '' : String(value)
  const [draft, setDraft] = useState(initial)
  const [shownFor, setShownFor] = useState(initial)
  if (shownFor !== initial) {
    setShownFor(initial)
    setDraft(initial)
  }
  const commit = () => {
    if (draft === initial) return
    if (draft.trim() === '') return onSave(undefined)
    const n = Math.round(Number(draft))
    if (!Number.isFinite(n)) return setDraft(initial)
    onSave(n)
  }
  return (
    <div className="node-seed">
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={draft}
        disabled={readOnly}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            commit()
          }
        }}
      />
      <button type="button" className="node-mini" disabled={readOnly} onClick={() => onSave(newSeed(value, min, max))}>
        Shuffle
      </button>
    </div>
  )
}
