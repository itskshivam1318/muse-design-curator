import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
  /** Its size on screen as drawn, reported as it changes (null once gone): floating cards keep off it. */
  /** Keep the selected plugin option as an ordinary item. */
  onKeep?: (itemId: string) => void
  /** Open the selected 3D item in the viewer. */
  onOpenModel?: (itemId: string) => void
  onSize?: (size: { width: number; height: number } | null) => void
}

export const COMPARE_MAX = 4
/** Screen px between the toolbar's bottom edge and the selection's top. */
export const TOOLBAR_GAP = 14

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
  onKeep,
  onOpenModel,
  onSize,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const onSizeRef = useRef(onSize)
  useLayoutEffect(() => {
    onSizeRef.current = onSize
  })
  // The bar is drawn upwards from `top` (translateY -100%), so its own height keeps it inside the stage.
  const [height, setHeight] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    onSizeRef.current?.({ width: el.offsetWidth, height: el.offsetHeight })
  })
  useLayoutEffect(() => setHeight(ref.current?.offsetHeight ?? 0), [])
  useEffect(() => {
    const el = ref.current
    const report = () => {
      if (!el) return
      onSizeRef.current?.({ width: el.offsetWidth, height: el.offsetHeight })
      setHeight(el.offsetHeight)
    }
    const ro = el && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(report) : null
    if (el) ro?.observe(el)
    return () => {
      ro?.disconnect()
      onSizeRef.current?.(null)
    }
  }, [])
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
      ref={ref}
      className="item-toolbar"
      role="toolbar"
      aria-label={single ? 'Item actions' : `${items.length} items selected`}
      style={{ left: screen.x + screen.width / 2, top: Math.max(8 + height, screen.y - TOOLBAR_GAP) }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {single?.option_run_id && onKeep && (
        <button type="button" className="is-primary" onClick={() => onKeep(single.id)} disabled={readOnly}>
          Keep
        </button>
      )}
      {single?.kind === 'model' && onOpenModel && (
        <button type="button" onClick={() => onOpenModel(single.id)}>
          Open 3D
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
