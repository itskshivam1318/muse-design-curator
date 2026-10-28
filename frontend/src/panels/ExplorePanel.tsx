import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  type AttributeSpec,
  type Exploration,
  type ExploreOption,
  exploreItem,
  keys,
  type Point,
  visualizeOption,
} from '../api'
import { placedNotes } from '../canvas/notes'
import { setHoveredOption, hoverStore, useHoveredOption } from '../explore/hover'
import { canFindReal, findRealRequest, optionTree, withExploration, withOption } from '../explore/logic'
import { dismissOption } from '../explore/optionActions'
import { itemTitle } from '../format'
import { useAttributes, useExplorations, useItems, useProfile } from '../queries'
import { isTension, numberBounds, sortTargets } from '../vary/logic'
import { startRun } from '../vary/startRun'
import { ValueText } from './AttrBits'
import type { DrawerPanelProps } from './drawerRegistry'
import { PanelHead } from './PanelHead'

/** Canvas notes open the panel focused on one attribute and option. */
interface ExploreParams {
  key?: string
  optionId?: string
}

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError || e instanceof Error ? e.message : fallback)

/** Explore: pick an attribute; its options list under it ("in the dimension"), with the same actions as the canvas notes. */
export function ExplorePanel({ boardId, itemId, params, onClose, locked = false }: DrawerPanelProps) {
  const preset = (params ?? {}) as ExploreParams
  const attrsQ = useAttributes(itemId)
  const profile = useProfile(boardId).data?.profile
  const items = useItems(boardId).data
  const item = items?.find((i) => i.id === itemId)
  const explorations = useExplorations(boardId).data
  // where the canvas draws each note (a never-dragged one's spot is only computed here)
  const drawn = useMemo(
    () => new Map(placedNotes(explorations ?? [], items ?? []).map((n) => [n.option.id, { x: n.x, y: n.y }])),
    [explorations, items],
  )
  const lens = attrsQ.data?.lens ?? null
  const records = useMemo(() => attrsQ.data?.attributes ?? [], [attrsQ.data])
  const byKey = useMemo(() => new Map(records.map((r) => [r.key, r])), [records])
  const labels = useMemo(() => new Map((lens?.attributes ?? []).map((a) => [a.key, a.label])), [lens])
  const targets = useMemo(
    () => sortTargets(lens?.attributes ?? [], profile).filter((a) => a.kind !== 'shape'),
    [lens, profile],
  )
  const [openKey, setOpenKey] = useState<string | null>(preset.key ?? null)

  return (
    <div className="panel explore-panel">
      <PanelHead eyebrow="Explore" title={item ? itemTitle(item) : 'Item'} onClose={onClose} />
      {attrsQ.isPending && <p className="muted panel-pad">Loading attributes…</p>}
      {attrsQ.isError && <p className="error panel-pad">Could not load attributes: {attrsQ.error.message}</p>}
      {attrsQ.isSuccess && !lens && <p className="muted panel-pad">Confirm this board's lens before exploring an item.</p>}
      {lens && (
        <div className="panel-body">
          <section className="step">
            <h3 className="eyebrow">What to explore</h3>
            {locked && <p className="note small">Demo — read-only: unlock to explore.</p>}
            <div className="explore-attrs">
              {targets.map((a) => {
                const r = byKey.get(a.key)
                const disabled = r ? !r.enabled : false
                const open = a.key === openKey
                const exploration = explorations?.find((e) => e.item_id === itemId && e.key === a.key)
                const count = exploration ? optionTree(exploration.options).length : 0
                return (
                  <div key={a.key} className={open ? 'explore-attr is-open' : 'explore-attr'}>
                    <button
                      type="button"
                      aria-expanded={open}
                      disabled={disabled}
                      className="target"
                      onClick={() => setOpenKey(open ? null : a.key)}
                    >
                      <span className="target-label">{a.label}</span>
                      {isTension(a.key, profile) && <span className="mark is-tension">tension</span>}
                      {count > 0 && <span className="mark">{count === 1 ? '1 option' : `${count} options`}</span>}
                      <span className="target-value">
                        {disabled ? (
                          'disabled'
                        ) : (
                          <ValueText kind={a.kind} value={r?.value ?? null} unit={numberBounds(a)?.unit} measured={r?.measured} />
                        )}
                      </span>
                    </button>
                    {open && !disabled && (
                      <Dimension
                        boardId={boardId}
                        itemId={itemId}
                        spec={a}
                        exploration={exploration}
                        labels={labels}
                        focusId={preset.key === a.key ? preset.optionId : undefined}
                        drawnAt={(id) => drawn.get(id)}
                        locked={locked}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

/** One attribute's options, branches indented under their parent, with More / Further / steer below. */
function Dimension({
  boardId,
  itemId,
  spec,
  exploration,
  labels,
  focusId,
  locked,
  drawnAt,
}: {
  boardId: string
  itemId: string
  spec: AttributeSpec
  exploration: Exploration | undefined
  labels: Map<string, string>
  focusId?: string
  locked: boolean
  drawnAt: (optionId: string) => Point | undefined
}) {
  const qc = useQueryClient()
  const hovered = useHoveredOption()
  const [steer, setSteer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const focusRef = useRef<HTMLLIElement>(null)
  const rows = useMemo(() => optionTree(exploration?.options ?? []), [exploration])

  useEffect(() => {
    focusRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [])

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

  const explore = (body: { mode?: 'initial' | 'more' | 'further'; parent_option_id?: string }) =>
    act(async () => {
      const s = steer.trim()
      const e = await exploreItem(itemId, { key: spec.key, ...body, ...(s ? { steer: s } : {}) })
      qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => withExploration(old, e))
      setSteer('')
    }, 'Could not explore')

  const visualize = (o: ExploreOption) =>
    act(async () => {
      // spin straight away; the server's explore.updated events then take over (done, or last_error)
      const key = keys.explorations(boardId)
      const set = (status: ExploreOption['status'], last_error: string | null) =>
        qc.setQueryData<Exploration[]>(key, (old) => {
          const cur = old?.flatMap((e) => e.options).find((x) => x.id === o.id) ?? o
          return withOption(old, { ...cur, status, last_error })
        })
      set('visualizing', null)
      try {
        await visualizeOption(o.id, drawnAt(o.id))
      } catch (e) {
        set(o.status, o.last_error)
        throw e
      }
    }, 'Could not visualize')

  const dismiss = (o: ExploreOption) =>
    act(() => dismissOption(qc, boardId, o), 'Could not dismiss')

  const findReal = (o: ExploreOption) =>
    act(async () => {
      await startRun(boardId, findRealRequest(itemId, spec.key, o))
    }, 'Could not start the run')

  const steerBox = (
    <input
      type="text"
      className="explore-steer"
      aria-label={`Steer ${spec.label}`}
      placeholder="What direction? (optional)"
      value={steer}
      disabled={locked}
      onChange={(e) => setSteer(e.target.value)}
    />
  )
  const errorLine = error && (
    <p className="error small" role="alert">
      {error}
    </p>
  )

  if (!exploration) {
    return (
      <div className="explore-dimension">
        {steerBox}
        {errorLine}
        <div className="row-end">
          <button type="button" className="btn" disabled={locked || busy} onClick={() => void explore({ mode: 'initial' })}>
            {busy ? 'Exploring…' : 'Explore'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="explore-dimension">
      {rows.length === 0 && <p className="muted small">Every option was dismissed. More brings new ones.</p>}
      <ul className="explore-options">
        {rows.map(({ option: o, depth }) => {
          const working = o.status === 'visualizing'
          const realOk = canFindReal(spec, o.value)
          const cls = ['explore-option', hovered === o.id && 'is-hovered', focusId === o.id && 'is-focused']
            .filter(Boolean)
            .join(' ')
          return (
            <li
              key={o.id}
              ref={focusId === o.id ? focusRef : undefined}
              className={cls}
              data-depth={depth}
              style={{ marginLeft: depth * 14 }}
              onMouseEnter={() => setHoveredOption(o.id)}
              onMouseLeave={() => {
                if (hoverStore.get() === o.id) setHoveredOption(null)
              }}
            >
              <div className="explore-option-head">
                <span className="explore-option-name">{o.name}</span>
                <span className={`mark is-${o.distance}`}>{o.distance}</span>
                {working && <span className="spinner" role="status" aria-label="Visualizing" />}
              </div>
              {o.description && <p className="explore-option-desc">{o.description}</p>}
              {o.keeps.length > 0 && (
                <p className="muted small">keeps: {o.keeps.map((k) => labels.get(k) ?? k).join(', ')}</p>
              )}
              {!working && o.last_error && <p className="error small">Couldn't visualize, try again.</p>}
              <div className="explore-actions">
                <button
                  type="button"
                  className="btn-quiet small"
                  aria-label={`Visualize ${o.name}`}
                  disabled={locked || busy || working}
                  onClick={() => void visualize(o)}
                >
                  Visualize
                </button>
                <button
                  type="button"
                  className="btn-quiet small"
                  aria-label={`Branch ${o.name}`}
                  disabled={locked || busy}
                  onClick={() => void explore({ parent_option_id: o.id })}
                >
                  Branch
                </button>
                <button
                  type="button"
                  className="btn-quiet small"
                  aria-label={`Find real examples ${o.name}`}
                  title={
                    realOk
                      ? undefined
                      : o.value === null
                        ? 'This option has no single value to search for.'
                        : `Not a known ${spec.label} value yet. Visualize it first to add it.`
                  }
                  disabled={locked || busy || !realOk}
                  onClick={() => void findReal(o)}
                >
                  Find real examples
                </button>
                <button
                  type="button"
                  className="btn-quiet small"
                  aria-label={`Dismiss ${o.name}`}
                  disabled={locked || busy}
                  onClick={() => void dismiss(o)}
                >
                  Dismiss
                </button>
              </div>
            </li>
          )
        })}
      </ul>
      <div className="explore-more">
        {steerBox}
        {errorLine}
        <div className="row-end">
          <button type="button" className="btn-quiet" disabled={locked || busy} onClick={() => void explore({ mode: 'more' })}>
            More
          </button>
          <button type="button" className="btn-quiet" disabled={locked || busy} onClick={() => void explore({ mode: 'further' })}>
            Further
          </button>
        </div>
      </div>
    </div>
  )
}
