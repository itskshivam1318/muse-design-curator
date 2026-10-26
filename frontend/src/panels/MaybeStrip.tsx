import { useState } from 'react'
import { type CandidateView, corpusImageUrl, type Item } from '../api'
import { useRun } from '../queries'
import { barState, progressText, runFailureText, shortfallText } from '../vary/logic'
import { runStore, useRunState } from '../vary/runStore'
import { startRun } from '../vary/startRun'
import { CandidatePopover } from './CandidatePopover'

interface Props {
  boardId: string
  /** Whether the board's event stream is connected; when it is not, the run is polled. */
  streamOpen: boolean
  onKept?: (item: Item, from: DOMRect | null) => void
}

/** Docked at the bottom: the active run's candidates, validated first, then Needs review. */
export function MaybeStrip({ boardId, streamOpen, onKept }: Props) {
  const { active, openCandidate } = useRunState()
  const runQ = useRun(active && active.boardId === boardId ? active.runId : null, streamOpen)
  const [why, setWhy] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)
  if (!active || active.boardId !== boardId) return null

  const data = runQ.data
  const status = data?.run.status
  const done = status === 'completed'
  const failed = status === 'failed'
  const results = data?.results ?? []
  const review = data?.needs_review ?? []
  const short = shortfallText(data?.summary)
  const all = [...results, ...review]
  const open = all.find((c) => c.id === openCandidate) ?? null
  const label = (c: CandidateView, i: number) =>
    `Candidate ${i + 1}, ${c.state === 'validated' ? 'validated' : 'needs review'}${c.decision ? `, ${c.decision.decision === 'keep' ? 'kept' : 'rejected'}` : ''}`

  const runAgain = async () => {
    setRetryError(null)
    try {
      await startRun(boardId, active.request)
    } catch (e) {
      setRetryError(e instanceof Error ? e.message : 'Could not start the run')
    }
  }

  const thumb = (c: CandidateView, i: number) => (
    <button
      key={c.id}
      type="button"
      className="strip-thumb"
      aria-label={label(c, i)}
      aria-expanded={openCandidate === c.id}
      data-decided={c.decision?.decision}
      onClick={() => runStore.open(openCandidate === c.id ? null : c.id)}
    >
      <img src={corpusImageUrl(c.corpus_item_id)} alt="" draggable={false} />
      <span className="strip-bar" data-state={barState(c.state) ?? undefined} aria-hidden="true" />
    </button>
  )

  return (
    <section className="maybe-strip" aria-label="Maybe strip">
      <div className="strip-meta">
        <span className="eyebrow">Maybe</span>
        <span className="strip-progress" role="status">
          {runQ.isError
            ? `Could not load the run: ${runQ.error.message}`
            : failed
              ? 'Failed'
              : done
                ? `${short.headline}${review.length ? ` ${review.length} to review.` : ''}`
                : progressText(data?.progress?.stage ?? 'queued', data?.progress?.validated_n, data?.progress?.shortlist_n)}
        </span>
        {done && short.link && all.length > 0 && (
          <button type="button" className="link-btn" aria-expanded={why} onClick={() => setWhy((w) => !w)}>
            {short.link}
          </button>
        )}
        <button type="button" className="icon-btn" aria-label="Close Maybe strip" onClick={() => runStore.clear()}>
          ×
        </button>
      </div>

      {failed ? (
        <p className="strip-empty">
          {runFailureText(data?.run.error_code)}{' '}
          <button type="button" className="link-btn" onClick={() => void runAgain()}>
            Run again
          </button>
          {retryError && <span className="error"> {retryError}</span>}
        </p>
      ) : done && all.length === 0 ? (
        <p className="strip-empty">
          {short.mostCommon
            ? `Nothing passed every check. Most common reason: ${short.mostCommon}.`
            : 'Nothing passed every check.'}
        </p>
      ) : (
        <div className="strip-row">
          {results.map(thumb)}
          {review.length > 0 && <span className="strip-divider">Needs review</span>}
          {review.map((c, i) => thumb(c, results.length + i))}
          {!done && all.length === 0 && <span className="strip-wait" aria-hidden="true" />}
        </div>
      )}

      {why && (
        <div className="shortfall" role="dialog" aria-label="Why fewer results">
          <p>
            <b>{short.headline}</b>
          </p>
          <ul>
            {short.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <button type="button" className="btn-quiet small" onClick={() => setWhy(false)}>
            Close
          </button>
        </div>
      )}

      {open && data && (
        <CandidatePopover
          key={open.id}
          boardId={boardId}
          runId={data.run.id}
          candidate={open}
          sourceItemId={data.run.source_item_id}
          targetKey={data.run.target_key}
          onClose={() => runStore.open(null)}
          onKept={onKept}
        />
      )}
    </section>
  )
}
