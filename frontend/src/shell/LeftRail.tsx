import type { ReactNode } from 'react'
import { RAIL_LABELS, type RailId } from './tools'

const svg = (children: ReactNode) => (
  <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
    {children}
  </svg>
)

const ICONS: Record<RailId, ReactNode> = {
  library: svg(
    <>
      <rect x="2.5" y="2.5" width="5.5" height="5.5" rx="1" />
      <rect x="10" y="2.5" width="5.5" height="5.5" rx="1" />
      <rect x="2.5" y="10" width="5.5" height="5.5" rx="1" />
      <rect x="10" y="10" width="5.5" height="5.5" rx="1" />
    </>,
  ),
  search: svg(
    <>
      <circle cx="8" cy="8" r="5" />
      <path d="M12 12l3.5 3.5" />
    </>,
  ),
  plugins: svg(<path d="M7 2.5h4v3a1.5 1.5 0 003 0V9h-3a1.5 1.5 0 000 3h3v3.5H2.5V9h3a1.5 1.5 0 000-3h-3V2.5H7z" />),
  vocabulary: (
    <span className="rail-aa" aria-hidden="true">
      Aa
    </span>
  ),
}

interface Props {
  open: RailId | null
  onOpen: (id: RailId | null) => void
  /** Plugins are on (server flag): show the Plugins icon. */
  plugins: boolean
}

/** Slim left rail: one 40 px icon button per slide-out panel; clicking the open one closes it. */
export function LeftRail({ open, onOpen, plugins }: Props) {
  const ids: RailId[] = plugins ? ['library', 'search', 'plugins', 'vocabulary'] : ['library', 'search', 'vocabulary']
  return (
    <nav className="left-rail" aria-label="Panels">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className="rail-btn"
          data-rail={id}
          aria-label={RAIL_LABELS[id]}
          title={RAIL_LABELS[id]}
          aria-pressed={open === id}
          onClick={() => onOpen(open === id ? null : id)}
        >
          {ICONS[id]}
        </button>
      ))}
    </nav>
  )
}
