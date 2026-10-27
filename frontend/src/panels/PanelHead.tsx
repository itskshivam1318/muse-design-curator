import type { ReactNode } from 'react'

export function PanelHead({
  eyebrow,
  title,
  onClose,
  sub,
}: {
  eyebrow: string
  title: string
  onClose: () => void
  /** A line under the title (e.g. an image credit). */
  sub?: ReactNode
}) {
  return (
    <header className="panel-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="panel-title">{title}</h2>
        {sub}
      </div>
      <button type="button" className="icon-btn" aria-label={`Close ${eyebrow.toLowerCase()}`} onClick={onClose}>
        ×
      </button>
    </header>
  )
}
