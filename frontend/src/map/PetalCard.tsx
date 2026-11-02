/**
 * The card a petal opens (Axis card artboard): what the option is and what it changes, one render
 * button named by what will run (or "Connect a renderer"), then the result's check with Keep / Not
 * this, or Retry / Drop when it drifted; always More like this, Branch and Dismiss.
 */
import { useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  type Exploration,
  type ExploreOption,
  exploreItem,
  type Item,
  itemImageUrl,
  keepTake,
  keys,
  type Point,
  visualizeOption,
} from '../api'
import { selection } from '../canvas/selection'
import { visualizeInProgress, withExploration, withOption } from '../explore/logic'
import { dismissOption } from '../explore/optionActions'
import { resultCheck } from '../explore/verdict'
import { useBoardLens, useExplorations, useItems, useRenderers } from '../queries'
import { openRail } from '../shell/tools'
import { changeExcerpt, isKept, resultOf } from './results'

export interface PetalDimension {
  key: string
  label: string
  /** The part a physical dimension lives on (its label); null for a whole-item dimension. */
  part: string | null
}

interface Props {
  option: ExploreOption
  dimension: PetalDimension
  /** The item the flower grows from. */
  item: Item
  /** Where a kept result goes: a free slot beside its petal. */
  keepAt: (result: Item) => Point
  onClose?: () => void
  /** Locked demo: readable, nothing changes. */
  locked?: boolean
}

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError || e instanceof Error ? e.message || fallback : fallback)

/** A result as a petal or the card shows it: the image, or the rewritten passage with its change marked. */
export function ResultPreview({ result, source, alt }: { result: Item; source: Item; alt: string }) {
  if (result.kind === 'note') {
    const x = changeExcerpt(source.note_text ?? '', result.note_text ?? '')
    return (
      <p className="petal-excerpt">
        {x.pre}
        <mark>{x.mark}</mark>
        {x.post}
      </p>
    )
  }
  return <img className="petal-img" src={itemImageUrl(result, 'thumb')} alt={alt} draggable={false} />
}

export function PetalCard({ option, dimension, item, keepAt, onClose, locked = false }: Props) {
  const boardId = item.board_id
  const qc = useQueryClient()
  const allItems = useItems(boardId).data
  const explorations = useExplorations(boardId).data
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])
  const renderers = useRenderers(item.id, dimension.key)
  const renderer = renderers.data?.[0]
  // the cache is newer than the props while a request settles
  const live = explorations?.flatMap((e) => e.options).find((o) => o.id === option.id) ?? option
  // results are staged items: not on the canvas, so read them from the full item list
  const byId = useMemo(() => new Map((allItems ?? []).map((i) => [i.id, i])), [allItems])
  const result = resultOf(live, byId)
  const kept = isKept(live)
  const rendering = live.status === 'visualizing'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // one request at a time, even when a second press lands before the re-render disables the button
  const inFlight = useRef(false)
  // focused when it opens, so Escape closes it straight away
  const cardRef = useRef<HTMLDivElement>(null)
  useEffect(() => cardRef.current?.focus(), [])

  const act = async (work: () => Promise<void>, fallback: string) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (e) {
      setError(errorText(e, fallback))
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const setOption = (o: ExploreOption) => qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withOption(old, o))

  const render = () =>
    act(async () => {
      if (!renderer) return
      // spin straight away; the server's explore.updated events then take over (done, or last_error)
      const before = live
      setOption({ ...live, status: 'visualizing', last_error: null })
      try {
        await visualizeOption(live.id, { renderer_id: renderer.id })
      } catch (e) {
        if (visualizeInProgress(e)) return // already running: its events end it
        setOption(before)
        throw e
      }
    }, 'Could not render')

  const keep = (take: Item) =>
    act(async () => {
      const at = keepAt(take)
      const next = await keepTake(live.id, take.id, at)
      setOption(next)
      // an ordinary board item now, where it was placed; any other kept take of the option goes back
      qc.setQueryData<Item[]>(keys.items(boardId), (old) =>
        old?.map((i) =>
          i.id === take.id
            ? { ...i, staged: false, ...at }
            : i.explore_option_id === live.id && !i.staged
              ? { ...i, staged: true }
              : i,
        ),
      )
      onClose?.()
    }, 'Could not keep')

  const dismiss = () =>
    act(async () => {
      await dismissOption(qc, boardId, live)
      onClose?.()
    }, 'Could not dismiss')

  const more = () =>
    act(async () => {
      const e = await exploreItem(item.id, { key: dimension.key, mode: 'more', parent_option_id: live.id })
      qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withExploration(old, e))
    }, 'Could not explore')

  // a kept result is a board item with its own callouts: branching is opening its dimensions
  const branch = () => {
    if (live.kept_item_id) selection.select([live.kept_item_id])
    onClose?.()
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    e.stopPropagation()
    onClose?.()
  }

  const check = result && !kept ? resultCheck(result.check, dimension.label, live.name, labels) : null
  const drifted = check?.tone === 'drift'

  return (
    <div
      ref={cardRef}
      className="petal-card"
      role="dialog"
      aria-label={live.name}
      tabIndex={-1}
      onKeyDown={onKeyDown} onMouseDown={(e) => e.stopPropagation()}>
      <div className="petal-card-head">
        <span className="petal-card-name">{live.name}</span>
        <span className="petal-tag" data-distance={live.distance}>
          {live.distance}
        </span>
      </div>
      {live.description && <p className="petal-card-desc">{live.description}</p>}
      <p className="petal-card-scope" data-testid="petal-scope">
        Changes <b>{dimension.part ?? dimension.label}</b> · keeps {live.keeps.length} ✓
      </p>

      {result && <ResultPreview result={result} source={item} alt={`${live.name} result`} />}
      {kept && <p className="petal-check is-ok">✓ kept · on the board</p>}
      {check && <p className={`petal-check is-${check.tone}`}>{check.text}</p>}

      {rendering ? (
        <p className="petal-progress" role="status">
          <span className="spinner" aria-hidden="true" /> Rendering {live.name}…
        </p>
      ) : (
        !result &&
        (renderers.isPending ? null : renderers.isError ? (
          <div className="petal-row">
            <p className="error small" role="alert">
              {errorText(renderers.error, 'Could not load the renderers')}
            </p>
            <button type="button" className="petal-secondary" onClick={() => void renderers.refetch()}>
              Retry
            </button>
          </div>
        ) : renderer ? (
          <button type="button" className="petal-render" disabled={locked || busy} onClick={() => void render()}>
            <span className="petal-render-title">{renderer.title}</span>
            <span className="petal-render-detail">{renderer.detail}</span>
          </button>
        ) : (
          <button type="button" className="petal-render is-connect" onClick={() => openRail('plugins')}>
            <span className="petal-render-title">Connect a renderer</span>
            <span className="petal-render-detail">opens the plugin picker</span>
          </button>
        ))
      )}

      {result && !kept && !rendering && (
        <div className="petal-row">
          {drifted ? (
            <>
              <button type="button" className="petal-primary" disabled={locked || busy || !renderer} onClick={() => void render()}>
                Retry
              </button>
              <button type="button" className="petal-secondary" disabled={locked || busy} onClick={() => void dismiss()}>
                Drop
              </button>
            </>
          ) : (
            <>
              <button type="button" className="petal-primary" disabled={locked || busy} onClick={() => void keep(result)}>
                Keep
              </button>
              <button type="button" className="petal-secondary" disabled={locked || busy} onClick={() => void dismiss()}>
                Not this
              </button>
            </>
          )}
        </div>
      )}
      {!rendering && live.last_error && <p className="error small">Couldn't render, try again.</p>}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      <div className="petal-more">
        <button type="button" className="btn-quiet small" disabled={locked || busy} onClick={() => void more()}>
          More like this
        </button>
        <button
          type="button"
          className="btn-quiet small"
          disabled={!kept}
          title={kept ? 'Select the kept result to explore it' : 'Keep a result to branch from it'}
          onClick={branch}
        >
          Branch
        </button>
        <button type="button" className="btn-quiet small" disabled={locked || busy} onClick={() => void dismiss()}>
          Dismiss
        </button>
      </div>
    </div>
  )
}
