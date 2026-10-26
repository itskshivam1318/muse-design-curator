export function PanelHead({ eyebrow, title, onClose }: { eyebrow: string; title: string; onClose: () => void }) {
  return (
    <header className="panel-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="panel-title">{title}</h2>
      </div>
      <button type="button" className="icon-btn" aria-label={`Close ${eyebrow.toLowerCase()}`} onClick={onClose}>
        ×
      </button>
    </header>
  )
}
