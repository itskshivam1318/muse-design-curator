import { useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useMemo, useState } from 'react'
import {
  ApiError,
  type Exploration,
  type ExploreOption,
  exploreItem,
  type Item,
  itemImageUrl,
  keepTake,
  keys,
  unkeepTake,
  visualizeOption,
} from '../api'
import { canFindReal, findRealRequest, optionTree, withExploration, withOption } from '../explore/logic'
import { dismissOption } from '../explore/optionActions'
import { verdictText } from '../explore/verdict'
import { useBoardLens, useExplorations, useItems } from '../queries'
import { startRun } from '../vary/startRun'
import { axisRows, cardOptionId, keptSlot } from './axis'
import { itemBounds } from './nodeProps'

interface Props {
  option: ExploreOption
  exploration: Exploration
  /** The image the axis comes from (as drawn, so a dragged source gives the slot it lands in). */
  source: Item
  onClose?: () => void
  /** Show another option of this exploration (a branch, or back to its parent). */
  onOpenOption?: (optionId: string) => void
  /** Locked demo: everything readable, nothing changes. */
  locked?: boolean
}

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError || e instanceof Error ? e.message : fallback)

/**
 * The popover under an axis card. Not visualized yet: what the option is and what it keeps, and
 * Visualize. Visualizing: progress. With takes: the current take with a pager, Keep or Un-keep,
 * Regenerate (another take) and the check's verdict. Branch, Find real examples and Dismiss always.
 */
export function AxisPopover({ option, exploration, source, onClose, onOpenOption, locked = false }: Props) {
  const boardId = exploration.board_id
  const qc = useQueryClient()
  const allItems = useItems(boardId).data
  const explorations = useExplorations(boardId).data
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])
  const spec = lensAttrs?.find((a) => a.key === exploration.key)
  const label = labels.get(exploration.key) ?? exploration.key
  // the cache is newer than the props while a request settles
  const exp = explorations?.find((e) => e.id === exploration.id) ?? exploration
  const live = exp.options.find((o) => o.id === option.id) ?? option
  // takes are staged items: not on the canvas, so read them from the full item list
  const byId = useMemo(() => new Map((allItems ?? []).map((i) => [i.id, i])), [allItems])
  const takes = live.takes.flatMap((id) => {
    const t = byId.get(id)
    return t ? [t] : []
  })
  const keptIndex = takes.findIndex((t) => t.id === live.kept_item_id)
  const [pager, setPager] = useState({ count: takes.length, index: keptIndex >= 0 ? keptIndex : takes.length - 1 })
  let index = pager.index
  if (pager.count !== takes.length) {
    // a new take arrived: show it; a take went away: stay in range
    index = takes.length > pager.count ? takes.length - 1 : Math.min(pager.index, takes.length - 1)
    setPager({ count: takes.length, index })
  }
  const current = index >= 0 ? takes[index] : undefined
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const rows = optionTree(exp.options)
  const at = rows.findIndex((r) => r.option.id === live.id)
  const branches: ExploreOption[] = []
  for (let i = at + 1; at >= 0 && i < rows.length && rows[i].depth > rows[at].depth; i++) {
    if (rows[i].depth === rows[at].depth + 1) branches.push(rows[i].option)
  }
  const parent = live.parent_option_id ? exp.options.find((o) => o.id === live.parent_option_id) : undefined

  const act = async (work: () => Promise<void>, fallback: string) => {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (e) {
      setError(errorText(e, fallback))
    } finally {
      setBusy(false)
    }
  }
  const setOption = (o: ExploreOption) =>
    qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withOption(old, o))
  const setItems = (f: (i: Item) => Item) => qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.map(f))

  const visualize = () =>
    act(async () => {
      // spin straight away; the server's explore.updated events then take over (done, or last_error)
      const before = live
      setOption({ ...live, status: 'visualizing', last_error: null })
      try {
        await visualizeOption(live.id)
      } catch (e) {
        setOption(before)
        throw e
      }
    }, 'Could not visualize')

  const keep = (take: Item) =>
    act(async () => {
      const mine = (explorations ?? [exp]).filter((e) => e.item_id === source.id)
      const row = axisRows(itemBounds(source), mine, labels).find((r) => r.exploration_id === exp.id)
      const slot = row ? keptSlot(row, cardOptionId(exp, live.id)) : undefined
      const next = await keepTake(live.id, take.id, slot)
      setOption(next)
      // exactly one kept take: it leaves the stage for its slot, any other goes back
      setItems((i) =>
        i.id === take.id
          ? { ...i, staged: false, ...(slot ?? {}) }
          : i.explore_option_id === live.id && !i.staged
            ? { ...i, staged: true }
            : i,
      )
      onClose?.()
    }, 'Could not keep')

  const unkeep = () =>
    act(async () => {
      const keptId = live.kept_item_id
      const next = await unkeepTake(live.id)
      setOption(next)
      setItems((i) => (i.id === keptId ? { ...i, staged: true } : i))
    }, 'Could not un-keep')

  const branch = () =>
    act(async () => {
      const e = await exploreItem(source.id, { key: exp.key, parent_option_id: live.id })
      qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withExploration(old, e))
    }, 'Could not branch')

  const findReal = () =>
    act(async () => {
      await startRun(boardId, findRealRequest(source.id, exp.key, live))
    }, 'Could not start the run')

  const dismiss = () =>
    act(async () => {
      await dismissOption(qc, boardId, live)
      onClose?.()
    }, 'Could not dismiss')

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.stopPropagation()
    onClose?.()
  }

  const working = live.status === 'visualizing'
  const realOk = !!spec && canFindReal(spec, live.value)
  const keeps = live.keeps.map((k) => labels.get(k) ?? k)
  const keepsLine = `${keeps.length ? `Keeps ${keeps.join(', ')}. ` : ''}Only ${label} changes.`
  const isKept = !!current && current.id === live.kept_item_id
  const verdict = current ? verdictText(current.check, label, live.name, labels) : null
  const caption = current ? `${live.name} · take ${index + 1}` : ''

  return (
    <div className="axis-popover" role="dialog" aria-label={live.name} onKeyDown={onKeyDown} onMouseDown={(e) => e.stopPropagation()}>
      {parent && (
        <button type="button" className="axis-pop-back" onClick={() => onOpenOption?.(parent.id)}>
          ‹ {parent.name}
        </button>
      )}
      {!current && (
        <>
          <p className="axis-pop-desc">
            <b>{live.name}</b>
            {live.description ? `: ${live.description}` : ''}
          </p>
          <p className="axis-pop-keeps">{keepsLine}</p>
          {working ? (
            <p className="axis-pop-progress" role="status">
              <span className="spinner" aria-hidden="true" /> Visualizing {live.name}…
            </p>
          ) : (
            <button type="button" className="axis-pop-primary" disabled={locked || busy} onClick={() => void visualize()}>
              Visualize
            </button>
          )}
        </>
      )}
      {current && (
        <>
          <div className="axis-take">
            <img src={itemImageUrl(current, 'thumb')} alt={caption} />
            <span className="axis-take-caption" aria-hidden="true">
              {caption}
            </span>
          </div>
          {takes.length > 1 && (
            <div className="axis-pager">
              <button
                type="button"
                aria-label="Previous take"
                disabled={index <= 0}
                onClick={() => setPager({ count: takes.length, index: index - 1 })}
              >
                ‹
              </button>
              <span>
                {index + 1} of {takes.length}
              </span>
              <button
                type="button"
                aria-label="Next take"
                disabled={index >= takes.length - 1}
                onClick={() => setPager({ count: takes.length, index: index + 1 })}
              >
                ›
              </button>
            </div>
          )}
          {verdict && <p className={`axis-pop-verdict verdict-${verdict.tone}`}>{verdict.text}</p>}
          {working && (
            <p className="axis-pop-progress" role="status">
              <span className="spinner" aria-hidden="true" /> Making take {takes.length + 1}…
            </p>
          )}
          <div className="axis-pop-row">
            <button
              type="button"
              className={isKept ? 'axis-pop-keep is-kept' : 'axis-pop-keep'}
              disabled={locked || busy}
              onClick={() => void (isKept ? unkeep() : keep(current))}
            >
              {isKept ? 'Un-keep' : 'Keep'}
            </button>
            <button type="button" className="axis-pop-regen" disabled={locked || busy || working} onClick={() => void visualize()}>
              Regenerate
            </button>
          </div>
        </>
      )}
      {!working && live.last_error && <p className="error small">Couldn't visualize, try again.</p>}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      {branches.length > 0 && (
        <ul className="axis-branches" aria-label={`Branches of ${live.name}`}>
          {branches.map((b) => (
            <li key={b.id}>
              <button type="button" onClick={() => onOpenOption?.(b.id)}>
                <span className="axis-branch-name">{b.name}</span>
                {b.description && <span className="axis-branch-desc">{b.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="axis-pop-more">
        <button type="button" className="btn-quiet small" disabled={locked || busy} onClick={() => void branch()}>
          Branch
        </button>
        <button
          type="button"
          className="btn-quiet small"
          title={
            realOk
              ? undefined
              : live.value === null
                ? 'This option has no single value to search for.'
                : `Not a known ${label} value yet. Visualize it first to add it.`
          }
          disabled={locked || busy || !realOk}
          onClick={() => void findReal()}
        >
          Find real examples
        </button>
        <button type="button" className="btn-quiet small" disabled={locked || busy} onClick={() => void dismiss()}>
          Dismiss
        </button>
      </div>
    </div>
  )
}
