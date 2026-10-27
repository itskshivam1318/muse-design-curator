import type { Item } from '../api'
import { safeExternalUrl } from '../format'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import type { Bounds } from './geometry'

interface Props {
  items: Item[]
  screen: Bounds
  /** Opens Explore (or Vary, when explore is off). */
  onExplore: () => void
  onInspect: () => void
  onCompare: () => void
  onNotThis: () => void
  onRemove: () => void
  /** Public demo, not unlocked: role changes and removal are disabled. */
  readOnly?: boolean
  /** Explore is on: the primary button reads Explore and opens the explore panel, else Vary. */
  explore?: boolean
}

export const COMPARE_MAX = 4

/**
 * Floating toolbar above the selection. One item: Explore (or Vary) · Inspect · Not this · Open source · Remove.
 * Several: Compare (2–4) · Not this · Remove. Panel buttons appear once their panels are registered.
 */
export function ItemToolbar({
  items,
  screen,
  onExplore,
  onInspect,
  onCompare,
  onNotThis,
  onRemove,
  readOnly = false,
  explore = false,
}: Props) {
  const primary = explore ? 'explore' : 'vary'
  const single = items.length === 1 ? items[0] : null
  const source = single ? (safeExternalUrl(single.page_url) ?? safeExternalUrl(single.source_url)) : null
  const allNot = items.every((i) => i.role === 'counter_example')
  const canPanel = single !== null && single.kind !== 'link'
  const canCompare = items.length >= 2 && items.length <= COMPARE_MAX && items.every((i) => i.kind !== 'link')
  return (
    <div
      className="item-toolbar"
      role="toolbar"
      aria-label={single ? 'Item actions' : `${items.length} items selected`}
      style={{ left: screen.x + screen.width / 2, top: Math.max(8, screen.y - 14) }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {canPanel && hasDrawerPanel(primary) && (
        <button type="button" className="is-primary" onClick={onExplore} aria-keyshortcuts="V">
          {explore ? 'Explore' : 'Vary'}
        </button>
      )}
      {canPanel && hasDrawerPanel('inspect') && (
        <button type="button" onClick={onInspect} aria-keyshortcuts="I">
          Inspect
        </button>
      )}
      {canCompare && hasDrawerPanel('compare') && (
        <button type="button" className="is-primary" onClick={onCompare}>
          Compare
        </button>
      )}
      <button type="button" onClick={onNotThis} aria-keyshortcuts="X" aria-pressed={allNot} disabled={readOnly}>
        {allNot ? 'Back to reference' : 'Not this'}
      </button>
      {source && (
        <a href={source} target="_blank" rel="noopener noreferrer">
          Open source ↗
        </a>
      )}
      <button type="button" onClick={onRemove} aria-keyshortcuts="Delete" disabled={readOnly}>
        Remove
      </button>
    </div>
  )
}
