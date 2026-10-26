import type { Item } from '../api'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import type { Bounds } from './geometry'

interface Props {
  items: Item[]
  screen: Bounds
  onVary: () => void
  onInspect: () => void
  onNotThis: () => void
  onRemove: () => void
}

/** Floating toolbar above the selection. Vary / Inspect appear once their panels are registered. */
export function ItemToolbar({ items, screen, onVary, onInspect, onNotThis, onRemove }: Props) {
  const single = items.length === 1 ? items[0] : null
  const source = single ? (single.page_url ?? single.source_url) : null
  const allNot = items.every((i) => i.role === 'counter_example')
  const canPanel = single !== null && single.kind !== 'link'
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
      <button type="button" onClick={onNotThis} aria-keyshortcuts="X" aria-pressed={allNot}>
        {allNot ? 'Back to reference' : 'Not this'}
      </button>
      {source && (
        <a href={source} target="_blank" rel="noopener noreferrer">
          Source ↗
        </a>
      )}
      <button type="button" onClick={onRemove} aria-keyshortcuts="Delete">
        Remove
      </button>
    </div>
  )
}
