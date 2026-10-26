import type { Item } from '../api'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import type { Bounds } from './geometry'

interface Props {
  items: Item[]
  screen: Bounds
  onVary: () => void
  onInspect: () => void
  onCompare: () => void
  onNotThis: () => void
  onRemove: () => void
}

export const COMPARE_MAX = 4

/**
 * Floating toolbar above the selection. One item: Vary · Inspect · Not this · Open source · Remove.
 * Several: Compare (2–4) · Not this · Remove. Panel buttons appear once their panels are registered.
 */
export function ItemToolbar({ items, screen, onVary, onInspect, onCompare, onNotThis, onRemove }: Props) {
  const single = items.length === 1 ? items[0] : null
  const source = single ? (single.page_url ?? single.source_url) : null
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
      {canPanel && hasDrawerPanel('vary') && (
        <button type="button" className="is-primary" onClick={onVary} aria-keyshortcuts="V">
          Vary
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
      <button type="button" onClick={onNotThis} aria-keyshortcuts="X" aria-pressed={allNot}>
        {allNot ? 'Back to reference' : 'Not this'}
      </button>
      {source && (
        <a href={source} target="_blank" rel="noopener noreferrer">
          Open source ↗
        </a>
      )}
      <button type="button" onClick={onRemove} aria-keyshortcuts="Delete">
        Remove
      </button>
    </div>
  )
}
