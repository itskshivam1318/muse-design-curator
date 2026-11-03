/**
 * Where a put-into result will land while its job runs: a dashed box the result's size, "Putting in…".
 * Its body is on the living board, so nothing overlaps it; the real picture replaces it through the
 * board's events. A failed job leaves a small error tile: Retry (the same request) or Dismiss.
 */
import { useRef, useState } from 'react'
import { ApiError, putInto } from '../api'
import { toScreenPoint, type View } from '../canvas/geometry'
import { useLiveBounds } from '../living/useLiveBounds'
import { ghostBodyId } from './bodies'
import { addGhost, failGhost, type Ghost, removeGhost } from './ghosts'

const FALLBACK = 'Could not put it in'
const errorText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message || FALLBACK : FALLBACK)

export function GhostTile({ ghost, view }: { ghost: Ghost; view: View }) {
  const live = useLiveBounds(ghostBodyId(ghost.jobId))
  const b = live ?? { x: ghost.x, y: ghost.y, width: ghost.w, height: ghost.h }
  const at = toScreenPoint({ x: b.x, y: b.y }, view)
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)

  const retry = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    const { targetId, body } = ghost.request
    try {
      const r = await putInto(targetId, body)
      removeGhost(ghost.jobId)
      addGhost({ ...ghost, jobId: r.job_id, x: r.x, y: r.y, w: r.w, h: r.h, error: null })
    } catch (e) {
      failGhost(ghost.jobId, errorText(e))
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const failed = ghost.error !== null
  return (
    <div
      className={failed ? 'put-ghost is-failed' : 'put-ghost'}
      style={{ left: at.x, top: at.y, width: b.width * view.scale, height: b.height * view.scale }}
      onPointerDown={failed ? (e) => e.stopPropagation() : undefined}
      onMouseDown={failed ? (e) => e.stopPropagation() : undefined}
    >
      {failed ? (
        <div className="put-ghost-error" role="alert">
          <p>{ghost.error || FALLBACK}</p>
          <div className="put-card-row">
            <button type="button" className="petal-primary" disabled={busy} onClick={() => void retry()}>
              Retry
            </button>
            <button type="button" className="petal-secondary" disabled={busy} onClick={() => removeGhost(ghost.jobId)}>
              Dismiss
            </button>
          </div>
        </div>
      ) : (
        <span className="put-ghost-label" role="status">
          Putting in…
        </span>
      )}
    </div>
  )
}
