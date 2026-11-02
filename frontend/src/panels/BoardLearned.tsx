import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { acceptOffer, declineOffer, keys, type Offer } from '../api'
import { useBoardContext } from '../queries'

type Decide = typeof acceptOffer

/** Under the person's words: what Muse has learned (read-only) and dimensions it offers to add. */
export function BoardLearned({ boardId, locked = false }: { boardId: string; locked?: boolean }) {
  const qc = useQueryClient()
  const context = useBoardContext(boardId)
  const [error, setError] = useState<string | null>(null)
  const data = context.data
  if (!data || (data.learned.length === 0 && data.offers.length === 0)) return null

  const decide = async (fn: Decide, o: Offer) => {
    setError(null)
    try {
      const next = await fn(boardId, { label: o.label, dim_type: o.dim_type, kind: o.kind, part: o.part })
      qc.setQueryData(keys.boardContext(boardId), next)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save')
    }
  }

  return (
    <div className="board-learned">
      {data.learned.length > 0 && (
        <>
          <h3 className="board-learned-title">What Muse has learned</h3>
          <ul className="board-learned-list">
            {data.learned.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
      {data.offers.map((o) => (
        <div key={`${o.dim_type}:${o.part ?? ''}:${o.label}`} className="board-offer">
          <span>
            {o.label} · seen on {o.count} of {o.total}
          </span>
          <button type="button" className="btn" disabled={locked} onClick={() => void decide(acceptOffer, o)}>
            Add to board
          </button>
          <button type="button" className="btn-quiet" disabled={locked} onClick={() => void decide(declineOffer, o)}>
            Keep item-only
          </button>
        </div>
      ))}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
