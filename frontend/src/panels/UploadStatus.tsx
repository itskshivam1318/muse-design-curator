import type { UploadJob } from '../canvas/useAddFlow'

/** Upload progress and per-file errors, above the + button. */
interface Props {
  jobs: UploadJob[]
  onDismiss: (id: number) => void
  onCancel: (id: number) => void
}

export function UploadStatus({ jobs, onDismiss, onCancel }: Props) {
  if (jobs.length === 0) return null
  return (
    <ul className="upload-status" aria-live="polite" aria-label="Uploads">
      {jobs.map((j) => (
        <li key={j.id} className={`upload is-${j.state}`}>
          <div className="upload-head">
            <span className="upload-label">
              {j.state === 'uploading' ? `Uploading ${j.label}` : j.state === 'done' ? `Added ${j.label}` : j.label}
            </span>
            {j.state === 'uploading' ? (
              <button
                type="button"
                className="btn-quiet small"
                aria-label={`Cancel uploading ${j.label}`}
                onClick={() => onCancel(j.id)}
              >
                Cancel
              </button>
            ) : (
              <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => onDismiss(j.id)}>
                ×
              </button>
            )}
          </div>
          {j.state === 'uploading' && (
            <progress max={1} value={j.progress} aria-label={`Uploading ${j.label}`}>
              {Math.round(j.progress * 100)}%
            </progress>
          )}
          {j.errors.length > 0 && (
            <ul className="upload-errors" role="alert">
              {j.errors.map((e, i) => (
                <li key={`${e.filename}-${i}`}>{e.message}</li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  )
}
