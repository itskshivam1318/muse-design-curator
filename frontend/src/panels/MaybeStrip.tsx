import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { type CandidateView, corpusImageUrl, type Item, type LiveSummary } from '../api'
import { useRun } from '../queries'
import { barState, findMoreLinks, progressText, runFailureText, shortfallText, sourceName, sourceStatusLines } from '../vary/logic'
import { runStore, useRunState } from '../vary/runStore'
import { startRun } from '../vary/startRun'
import { useDialog } from '../ui/useDialog'
import { track } from '../telemetry'

const CandidatePopover = lazy(() => import('./CandidatePopover').then((m) => ({ default: m.CandidatePopover })))

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
  const shownRunId = active && active.boardId === boardId && runQ.data?.run.status === 'completed' ? active.runId : null
  const shownLogged = useRef<string | null>(null)
  const shownData = shownRunId ? runQ.data : undefined
  useEffect(() => {
    if (!shownRunId || !shownData || shownLogged.current === shownRunId) return
    shownLogged.current = shownRunId // once per completed run
    track('run.shown', {
      runId: shownRunId,
      detail: { results: shownData.results?.length ?? 0, needs_review: shownData.needs_review?.length ?? 0 },
    })
  }, [shownRunId, shownData])
  if (!active || active.boardId !== boardId) return null

  const data = runQ.data
  const status = data?.run.status
  const done = status === 'completed'
  const failed = status === 'failed'
  const results = data?.results ?? []
  const review = data?.needs_review ?? []
  const short = shortfallText(data?.summary)
  const findMore = findMoreLinks(data?.summary?.live?.queries)
  const all = [...results, ...review]
  const liveSources = Object.entries(data?.summary?.live?.sources ?? data?.progress?.live?.sources ?? {})
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
      data-origin={c.origin}
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
                : progressText(data?.progress?.stage ?? 'queued', data?.progress?.validated_n, data?.progress?.shortlist_n, data?.progress?.live)}
        </span>
        {liveSources.length > 0 && (
          <span className="source-chips" role="group" aria-label="Live sources">
            {liveSources.map(([id, st]) => (
              <span key={id} className="source-chip" data-status={st}>
                {sourceName(id)}
              </span>
            ))}
          </span>
        )}
        {done && short.link && all.length > 0 && (
          <button type="button" className="link-btn" aria-expanded={why} onClick={() => {
              if (!why) track('run.why_only', { runId: active?.runId, detail: { returned: data?.summary?.returned ?? null } })
              setWhy((w) => !w)
            }}>
            {short.link}
          </button>
        )}
        {done && findMore.length > 0 && (
          <span className="find-more small" title="Opens in a new tab. Save what you like with the Chrome extension; it stays a private reference on this board.">
            Find more:{' '}
            {findMore.map((l, i) => (
              <span key={l.site}>
                {i > 0 && ' · '}
                <a
                  href={l.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => track('run.find_more', { runId: active?.runId, detail: { site: l.site } })}
                >
                  {l.site} ↗
                </a>
              </span>
            ))}
          </span>
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

      {why && <ShortfallDialog headline={short.headline} lines={short.lines} live={data?.summary?.live} onClose={() => setWhy(false)} />}

      {open && data && (
        <Suspense fallback={<p className="muted small">Loading…</p>}>
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
        </Suspense>
      )}
    </section>
  )
}

function ShortfallDialog({ headline, lines, live, onClose }: { headline: string; lines: string[]; live?: LiveSummary; onClose: () => void }) {
  const dialog = useDialog<HTMLDivElement>(onClose)
  return (
    <div className="shortfall" aria-label="Why fewer results" {...dialog}>
      <p>
        <b>{headline}</b>
      </p>
      <ul>
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      {live && (
        <>
          <p className="small muted">{`Found ${live.found} live, ${live.kept} kept.`}</p>
          <ul className="source-status" aria-label="Live sources">
            {sourceStatusLines(live).map((l) => (
              <li key={l} className="small">
                {l}
              </li>
            ))}
          </ul>
        </>
      )}
      <button type="button" className="btn-quiet small" data-autofocus onClick={onClose}>
        Close
      </button>
    </div>
  )
}
