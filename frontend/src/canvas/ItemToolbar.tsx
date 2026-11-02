import { useState } from 'react'
import type { Item } from '../api'
import { safeExternalUrl } from '../format'
import { hasDrawerPanel } from '../panels/drawerRegistry'
import type { Bounds } from './geometry'

interface Props {
  items: Item[]
  screen: Bounds
  onInspect: () => void
  onCompare: () => void
  onNotThis: () => void
  onRemove: () => void
  /** Analyse the one selected item again; rejects with the refusal (e.g. the daily limit). */
  onReanalyse?: (itemId: string) => Promise<unknown>
  /** Public demo, not unlocked: role changes and removal are disabled. */
  readOnly?: boolean
}

export const COMPARE_MAX = 4

/**
 * Floating toolbar above the selection. One item: Inspect · Re-analyse · Not this · Remove (+ Open
 * source); Re-analyse is on images and videos on the board (not staged takes).
 * Several: Compare (2–4) · Not this · Remove. Panel buttons appear once their panels are registered.
 */
export function ItemToolbar({
  items,
  screen,
  onInspect,
  onCompare,
  onNotThis,
  onRemove,
  onReanalyse,
  readOnly = false,
}: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<{ id: string; text: string } | null>(null)
  const single = items.length === 1 ? items[0] : null
  const source = single ? (safeExternalUrl(single.page_url) ?? safeExternalUrl(single.source_url)) : null
  const allNot = items.every((i) => i.role === 'counter_example')
  const canPanel = single !== null && single.kind !== 'link'
  const canReanalyse =
    single !== null && onReanalyse !== undefined && !single.staged && ['image', 'video'].includes(single.kind)
  const analysing = single !== null && (single.parse_status === 'pending' || single.parse_status === 'processing')
  const reanalyse = async (id: string) => {
    setBusy(id)
    setRefusal(null)
    try {
      await onReanalyse?.(id)
    } catch (e) {
      setRefusal({ id, text: e instanceof Error && e.message ? e.message : 'Could not analyse again' })
    } finally {
      setBusy(null)
    }
  }
  const canCompare = items.length >= 2 && items.length <= COMPARE_MAX && items.every((i) => i.kind !== 'link')
  return (
    <div
      className="item-toolbar"
      role="toolbar"
      aria-label={single ? 'Item actions' : `${items.length} items selected`}
      style={{ left: screen.x + screen.width / 2, top: Math.max(8, screen.y - 14) }}
      onMouseDown={(e) => e.stopPropagation()}
    >
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
      {canReanalyse && (
        <button
          type="button"
          className="is-reanalyse"
          onClick={() => void reanalyse(single.id)}
          disabled={readOnly || busy !== null || analysing}
          aria-busy={busy === single.id || analysing}
          title={analysing ? 'Muse is analysing this item' : 'Read this item again'}
        >
          Re-analyse
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
      {single && refusal?.id === single.id && (
        <p className="item-toolbar-error" role="alert">
          {refusal.text}
        </p>
      )}
    </div>
  )
}
