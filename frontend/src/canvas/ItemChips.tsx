import { useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { ApiError, type AttributeSpec, type Exploration, exploreItem, type Item, type ItemAttribute, keys } from '../api'
import { withExploration } from '../explore/logic'
import { ValueText } from '../panels/AttrBits'
import { useAttributes, useExplorations } from '../queries'
import { numberBounds } from '../vary/logic'
import { cardOptions, chipSource, focusAxis } from './axis'
import type { Bounds } from './geometry'
import { useSelection } from './selection'

const MAX_CHIPS = 6
const GAP = 8
/** Room for the credit or "generated" caption that sits under such an image. */
const CAPTION_H = 30

/**
 * The attributes an image can be explored on: the lens's own (a plugin's extra attributes stay
 * in Inspect, the server refuses to explore them), enabled, never shapes, in lens order.
 */
const explorable = (records: readonly ItemAttribute[], lens: readonly AttributeSpec[] | undefined) => {
  const keys = new Set((lens ?? []).map((s) => s.key))
  return records.filter((r) => keys.has(r.key) && r.enabled && r.kind !== 'shape')
}

const errorText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : 'Could not explore')

/** Explore one attribute of an item: focus its axis when it has one, else ask for options first. */
function useExploreKey(item: Item) {
  const qc = useQueryClient()
  const explorations = useExplorations(item.board_id).data
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const explore = async (key: string): Promise<boolean> => {
    const live = explorations?.find((e) => e.item_id === item.id && e.key === key && cardOptions(e).length > 0)
    if (live) {
      focusAxis(live.id)
      return true
    }
    setBusy(key)
    setError(null)
    try {
      const e = await exploreItem(item.id, { key, mode: 'initial' })
      qc.setQueryData<Exploration[]>(keys.explorations(item.board_id), (old) => withExploration(old, e))
      focusAxis(e.id)
      return true
    } catch (e) {
      setError(errorText(e))
      return false
    } finally {
      setBusy(null)
    }
  }
  return { busy, error, explore }
}

function Chip({
  a,
  spec,
  busy,
  disabled,
  onClick,
}: {
  a: ItemAttribute
  spec: AttributeSpec | undefined
  busy: boolean
  disabled: boolean
  onClick: () => void
}) {
  const source = chipSource(a)
  return (
    <button type="button" className="item-chip" data-key={a.key} disabled={disabled} aria-busy={busy} onClick={onClick}>
      <span className="chip-mark" data-source={source} title={source} aria-hidden="true" />
      <span className="chip-label">{a.label}</span>
      <span className="chip-value">
        {busy ? 'exploring…' : <ValueText kind={a.kind} value={a.value} unit={numberBounds(spec)?.unit} measured={a.measured} />}
      </span>
      <span className="sr-only">, {source}</span>
    </button>
  )
}

/**
 * Up to six attribute chips under the selected image, each marked with where its value came
 * from. A chip explores that attribute: the options appear as an axis beside the image.
 */
export function ItemChips({ item, screen, locked = false }: { item: Item; screen: Bounds; locked?: boolean }) {
  const { selected } = useSelection()
  const sole = selected.length === 1 && selected[0] === item.id && item.kind === 'image'
  const data = useAttributes(sole ? item.id : null).data
  const records = data?.attributes
  const specs = new Map((data?.lens?.attributes ?? []).map((s) => [s.key, s]))
  const { busy, error, explore } = useExploreKey(item)
  if (!sole || !records) return null
  const chips = explorable(records, data?.lens?.attributes).slice(0, MAX_CHIPS)
  if (chips.length === 0) return null
  const below = item.licence || item.origin === 'generated' ? CAPTION_H : 0
  return (
    <div
      className="item-chips"
      role="group"
      aria-label="Explore an attribute"
      style={{ left: screen.x, top: screen.y + screen.height + GAP + below, maxWidth: Math.max(screen.width, 260) }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {chips.map((a) => (
        <Chip key={a.key} a={a} spec={specs.get(a.key)} busy={busy === a.key} disabled={locked || busy !== null} onClick={() => void explore(a.key)} />
      ))}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * The Axis tool on a selected image: its attributes in a popover at the image's right edge.
 * Picking one explores it (or focuses the axis it already has) and hands back to Select.
 */
export function AxisPicker({
  item,
  screen,
  onDone,
  locked = false,
}: {
  item: Item
  screen: Bounds
  onDone: () => void
  locked?: boolean
}) {
  const q = useAttributes(item.id)
  const { busy, error, explore } = useExploreKey(item)
  const first = useRef<HTMLButtonElement>(null)
  const records = q.data?.attributes
  const ready = !!records
  useEffect(() => {
    if (ready) first.current?.focus()
  }, [ready])
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.stopPropagation()
    onDone()
  }
  const options = explorable(records ?? [], q.data?.lens?.attributes)
  const specs = new Map((q.data?.lens?.attributes ?? []).map((s) => [s.key, s]))
  return (
    <div
      className="axis-popover axis-picker"
      role="dialog"
      aria-label="Pick an attribute to explore"
      style={{ left: screen.x + screen.width + 12, top: screen.y }}
      onKeyDown={onKeyDown}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {q.isPending && <p className="muted small">Loading attributes…</p>}
      {q.data && !q.data.lens && <p className="muted small">Confirm this board's lens before exploring an item.</p>}
      {q.data?.lens && (
        <ul className="axis-picker-list">
          {options.map((a, i) => (
            <li key={a.key}>
              <button
                ref={i === 0 ? first : undefined}
                type="button"
                disabled={locked || busy !== null}
                onClick={async () => {
                  if (await explore(a.key)) onDone()
                }}
              >
                <span className="chip-label">{a.label}</span>
                <span className="chip-value">
                  {busy === a.key ? 'exploring…' : <ValueText kind={a.kind} value={a.value} unit={numberBounds(specs.get(a.key))?.unit} measured={a.measured} />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
