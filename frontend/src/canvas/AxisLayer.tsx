import { useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, type WheelEvent, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { ApiError, type Exploration, type ExploreOption, exploreItem, type Item, itemImageUrl, keys } from '../api'
import { hoverStore, setHoveredOption, useHoveredOption } from '../explore/hover'
import { withExploration } from '../explore/logic'
import { verdictText } from '../explore/verdict'
import { useBoardLens } from '../queries'
import { type AxisCard, type AxisRow, cardOptions, cardOptionId, drawnAxes, focusAxis, focusStore, keptOnCard } from './axis'
import { AxisPopover } from './AxisPopover'
import { selection } from './selection'
import type { View } from './geometry'

/** The axis a chip, the picker or a card click chose last. */
const useFocusedAxis = () => useSyncExternalStore(focusStore.subscribe, focusStore.get)

interface Props {
  /** The canvas's visible items, as drawn (a dragged source carries its axes along). */
  items: readonly Item[]
  explorations: readonly Exploration[]
  /** The one selected item, if any: its axes use the accent. */
  selectedId: string | null
  view: View
  locked?: boolean
  /** Wheel over a card pans or zooms the canvas like anywhere else. */
  onWheel?: (e: WheelEvent) => void
}

/**
 * Every explore axis on the board, as HTML over the canvas (real buttons, reachable by keyboard):
 * the line, its label, the text cards (a kept option shows its kept take instead) and the end
 * handle. Clicking a card opens its popover; the end handle opens More / Further / steer.
 */
export function AxisLayer(props: Props) {
  if (props.explorations.length === 0) return null
  return <Axes {...props} boardId={props.explorations[0].board_id} />
}

type Open = { kind: 'card'; explorationId: string; optionId: string } | { kind: 'end'; explorationId: string }

function Axes({ items, explorations, selectedId, view, locked = false, onWheel, boardId }: Props & { boardId: string }) {
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])
  const { axes } = useMemo(() => drawnAxes(items, explorations, labels), [items, explorations, labels])
  const visible = useMemo(() => new Map(items.filter((i) => !i.staged).map((i) => [i.id, i])), [items])
  const focusedAxis = useFocusedAxis()
  const hovered = useHoveredOption()
  const [open, setOpen] = useState<Open | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  // a click anywhere else closes the popover
  useEffect(() => {
    if (!open) return
    const down = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', down)
    return () => document.removeEventListener('mousedown', down)
  }, [open])

  const find = (explorationId: string) => {
    for (const a of axes) {
      const row = a.rows.find((r) => r.exploration_id === explorationId)
      if (row) return { axis: a, row, exploration: a.explorations.find((e) => e.id === explorationId)! }
    }
    return null
  }
  const screenOf = (x: number, y: number) => ({ left: view.x + x * view.scale, top: view.y + y * view.scale })

  let popover = null
  if (open) {
    const found = find(open.explorationId)
    if (found && open.kind === 'card') {
      const option = found.exploration.options.find((o) => o.id === open.optionId && o.status !== 'dismissed')
      const card = found.row.cards.find((c) => c.option_id === cardOptionId(found.exploration, open.optionId))
      if (option && card) {
        // a selected kept take has its toolbar above the card and chips below it: the popover goes beside
        const keptSelected = keptOnCard(found.exploration, card.option_id, visible)?.item.id === selectedId
        const at = keptSelected ? screenOf(card.x + card.w + 8, card.y) : screenOf(card.x, card.y + card.h + 8)
        popover = (
          <div className="axis-pop-anchor" style={at}>
            <AxisPopover
              key={option.id}
              option={option}
              exploration={found.exploration}
              source={found.axis.source}
              locked={locked}
              onClose={() => setOpen(null)}
              onOpenOption={(id) => setOpen({ kind: 'card', explorationId: open.explorationId, optionId: id })}
            />
          </div>
        )
      }
    } else if (found && open.kind === 'end') {
      popover = (
        <div className="axis-pop-anchor" style={screenOf(found.row.x1 - 10, found.row.y + 16)}>
          <AxisEnd
            source={found.axis.source}
            row={found.row}
            locked={locked}
            onClose={() => setOpen(null)}
          />
        </div>
      )
    }
  }

  return (
    <div ref={rootRef} className="axis-layer" onWheel={onWheel}>
      <div
        className="axis-world"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
      >
        {axes.map((a) => {
          const own = new Set(a.rows.map((r) => r.exploration_id))
          return a.rows.map((row) => {
            const exploration = a.explorations.find((e) => e.id === row.exploration_id)!
            const keptHere = row.cards.some((c) => keptOnCard(exploration, c.option_id, visible)?.item.id === selectedId)
            const active =
              keptHere ||
              (a.source.id === selectedId && (focusedAxis === row.exploration_id || !own.has(focusedAxis ?? '')))
            return (
              <AxisRowView
                key={row.exploration_id}
                row={row}
                exploration={exploration}
                active={active}
                visible={visible}
                labels={labels}
                hovered={hovered}
                selectedId={selectedId}
                openOption={open?.kind === 'card' && open.explorationId === row.exploration_id ? cardOptionId(exploration, open.optionId) : null}
                endOpen={open?.kind === 'end' && open.explorationId === row.exploration_id}
                onCard={(optionId, keptItemId) => {
                  focusAxis(row.exploration_id)
                  // a kept take is a board item: its card selects it (toolbar, chips, Delete, Inspect…)
                  if (keptItemId) selection.select([keptItemId])
                  setOpen((cur) =>
                    cur?.kind === 'card' &&
                    cur.explorationId === row.exploration_id &&
                    cardOptionId(exploration, cur.optionId) === cardOptionId(exploration, optionId)
                      ? null
                      : { kind: 'card', explorationId: row.exploration_id, optionId },
                  )
                }}
                onEnd={() => {
                  focusAxis(row.exploration_id)
                  setOpen((cur) =>
                    cur?.kind === 'end' && cur.explorationId === row.exploration_id ? null : { kind: 'end', explorationId: row.exploration_id },
                  )
                }}
              />
            )
          })
        })}
      </div>
      {popover}
    </div>
  )
}

function AxisRowView({
  row,
  exploration,
  active,
  visible,
  labels,
  hovered,
  selectedId,
  openOption,
  endOpen,
  onCard,
  onEnd,
}: {
  row: AxisRow
  exploration: Exploration
  active: boolean
  visible: ReadonlyMap<string, Item>
  labels: ReadonlyMap<string, string>
  hovered: string | null
  selectedId: string | null
  openOption: string | null
  endOpen: boolean
  onCard: (optionId: string, keptItemId?: string) => void
  onEnd: () => void
}) {
  const options = new Map(cardOptions(exploration).map((o) => [o.id, o]))
  return (
    <div className={active ? 'axis-row is-active' : 'axis-row'} data-exploration-id={row.exploration_id}>
      <span className="axis-label" style={{ left: row.x0, top: row.y - 20 }}>
        {row.label}
      </span>
      <div
        className="axis-line"
        data-active={active ? 'true' : 'false'}
        style={{ left: row.x0, top: row.y - 0.75, width: row.x1 - row.x0 }}
        aria-hidden="true"
      />
      {row.cards.map((card) => {
        const option = options.get(card.option_id)
        if (!option) return null
        const kept = keptOnCard(exploration, option.id, visible)
        return (
          <CardButton
            key={card.option_id}
            card={card}
            option={option}
            kept={kept}
            verdict={kept ? verdictText(kept.item.check, row.label, kept.option.name, labels).text : null}
            pressed={openOption === option.id}
            selected={!!kept && kept.item.id === selectedId}
            hovered={hovered === option.id || (!!kept && hovered === kept.option.id)}
            // a kept card opens on the option whose take it shows (a branch's, maybe)
            onClick={() => (kept ? onCard(kept.option.id, kept.item.id) : onCard(option.id))}
          />
        )
      })}
      <button
        type="button"
        className="axis-end"
        aria-label={`More ${row.label} options`}
        aria-expanded={endOpen}
        style={{ left: row.x1 - 10, top: row.y - 10 }}
        onClick={onEnd}
      />
    </div>
  )
}

function CardButton({
  card,
  option,
  kept,
  verdict,
  pressed,
  selected,
  hovered,
  onClick,
}: {
  card: AxisCard
  option: ExploreOption
  kept: { option: ExploreOption; item: Item } | null
  verdict: string | null
  pressed: boolean
  selected: boolean
  hovered: boolean
  onClick: () => void
}) {
  const cls = ['axis-card', kept ? 'is-kept' : 'is-text', pressed && 'is-open', selected && 'is-selected', hovered && 'is-hovered']
    .filter(Boolean)
    .join(' ')
  const status = option.status === 'visualizing' ? 'visualizing' : option.last_error ? "couldn't visualize" : null
  return (
    <button
      type="button"
      className={cls}
      data-testid="axis-card"
      data-option-id={option.id}
      aria-pressed={pressed}
      title={kept ? (verdict ?? undefined) : `${option.distance}${option.status === 'open' ? '' : ` · ${option.status}`}`}
      style={{ left: card.x, top: card.y, width: card.w, minHeight: card.h }}
      onMouseEnter={() => setHoveredOption(option.id)}
      onMouseLeave={() => {
        if (hoverStore.get() === option.id) setHoveredOption(null)
      }}
      onFocus={() => setHoveredOption(option.id)}
      onBlur={() => {
        if (hoverStore.get() === option.id) setHoveredOption(null)
      }}
      onClick={onClick}
    >
      {kept ? (
        <>
          <img className="axis-thumb" src={itemImageUrl(kept.item, 'thumb')} alt="" width={84} height={84} draggable={false} />
          <span className="axis-kept-name">
            {kept.option.name} <span className="axis-kept-tag">· kept</span>
          </span>
        </>
      ) : (
        <>
          <span className="axis-card-name">
            <span className="axis-dot" data-distance={option.distance} aria-hidden="true" />
            {option.name}
          </span>
          {option.description && <span className="axis-card-desc">{option.description}</span>}
          {status && <span className="axis-card-status">{status}…</span>}
        </>
      )}
    </button>
  )
}

const errorText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : 'Could not explore')

/** The end handle's controls: steer, then More (another batch) or Further (bolder ones). */
function AxisEnd({ source, row, locked, onClose }: { source: Item; row: AxisRow; locked: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [steer, setSteer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = async (mode: 'more' | 'further') => {
    setBusy(true)
    setError(null)
    try {
      const s = steer.trim()
      const e = await exploreItem(source.id, { key: row.key, mode, ...(s ? { steer: s } : {}) })
      qc.setQueryData<Exploration[]>(keys.explorations(source.board_id), (old) => withExploration(old, e))
      onClose()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.stopPropagation()
    onClose()
  }
  return (
    <div className="axis-popover axis-end-pop" role="dialog" aria-label={`More ${row.label} options`} onKeyDown={onKeyDown} onMouseDown={(e) => e.stopPropagation()}>
      <input
        type="text"
        className="explore-steer"
        aria-label={`Steer ${row.label}`}
        placeholder="What direction? (optional)"
        value={steer}
        disabled={locked}
        onChange={(e) => setSteer(e.target.value)}
      />
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      <div className="axis-pop-row">
        <button type="button" className="axis-pop-regen" disabled={locked || busy} onClick={() => void run('more')}>
          More
        </button>
        <button type="button" className="axis-pop-regen" disabled={locked || busy} onClick={() => void run('further')}>
          Further
        </button>
      </div>
    </div>
  )
}

