/**
 * A plugin node on the canvas, as HTML over the stage (real buttons, reachable by keyboard): header
 * (drag to move), input chips, the settings line and its fields, the output area, Run and the
 * plugin's secondary action. Nothing is generated until Run is clicked.
 */
import { useQueryClient } from '@tanstack/react-query'
import { type KeyboardEvent, type PointerEvent as ReactPointerEvent, type WheelEvent, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  type Item,
  itemImageUrl,
  keys,
  type NodesResponse,
  type PluginInfo,
  type PluginNode,
  type PluginRun,
  runNode,
} from '../api'
import { toScreenBounds, type View } from '../canvas/geometry'
import { LOCKED_TITLE } from '../demo'
import { itemTitle } from '../format'
import { canRun, effective, type Field, nodeBounds, paramFields, previewNode, removeNode, shownFields, summaryLine, updateNode } from './nodeLogic'
import { PluginTile } from './PluginsPanel'

interface Props {
  boardId: string
  node: PluginNode
  plugin: PluginInfo | undefined
  /** The node's latest run, if any. */
  run: PluginRun | undefined
  /** The board's visible items by id (inputs that are gone show as removed). */
  items: ReadonlyMap<string, Item>
  view: View
  readOnly?: boolean
  /** The node an item drag is over: it takes the items on release. */
  dropTarget?: boolean
  onWheel?: (e: WheelEvent) => void
}

const ACTIVE = new Set(['queued', 'running'])
const short = (s: string, n = 22) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s)
const inputLabel = (item: Item | undefined): string =>
  !item ? 'removed item' : item.kind === 'note' ? (item.note_text ?? '').trim() || 'note' : itemTitle(item)

function Dots() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d="M3.5 8h.01M8 8h.01M12.5 8h.01" />
    </svg>
  )
}
function Cross() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M2 2l6 6M8 2L2 8" />
    </svg>
  )
}

function Chip({ item, label, onRemove, readOnly }: { item: Item | undefined; label: string; onRemove: () => void; readOnly: boolean }) {
  const thumb =
    item && (item.kind === 'image' || item.kind === 'video') && item.thumb_path ? (
      <img className="node-chip-thumb" src={itemImageUrl(item, 'thumb')} alt="" />
    ) : (
      <span className={`node-chip-thumb is-${item?.kind ?? 'removed'}`} aria-hidden="true" />
    )
  return (
    <li className={item ? 'node-chip' : 'node-chip is-removed'} title={label}>
      {thumb}
      <span className="node-chip-label">{short(label)}</span>
      <button
        type="button"
        className="node-chip-remove"
        aria-label={`Remove input ${label}`}
        disabled={readOnly}
        onClick={onRemove}
      >
        <Cross />
      </button>
    </li>
  )
}

function Table({ value }: { value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) return null
  const objects = value.every((r) => typeof r === 'object' && r !== null && !Array.isArray(r))
  const head = objects ? [...new Set(value.flatMap((r) => Object.keys(r as object)))] : null
  const rows: unknown[][] = objects
    ? value.map((r) => head!.map((k) => (r as Record<string, unknown>)[k]))
    : value.map((r) => (Array.isArray(r) ? r : [r]))
  const cell = (v: unknown) => (v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v))
  return (
    <table className="node-table">
      {head && (
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
      )}
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (
              <td key={j}>{cell(c)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Output({ plugin, run, items, running }: { plugin: PluginInfo | undefined; run: PluginRun | undefined; items: ReadonlyMap<string, Item>; running: boolean }) {
  if (plugin && plugin.status !== 'available') return <p className="node-output-empty">{plugin.runs_on} not connected</p>
  if (running) {
    const message = run?.progress?.message ?? (run?.status === 'running' ? 'Running…' : 'Starting…')
    return (
      <div className="node-progress">
        <div className="node-progress-bar" role="progressbar" aria-label={`${plugin?.name ?? 'Plugin'} running`} aria-valuetext={message}>
          <span />
        </div>
        <p className="node-progress-text" aria-live="polite">
          {message}
        </p>
      </div>
    )
  }
  if (!run) return <p className="node-output-empty">The output appears here after Run.</p>
  if (run.status === 'failed')
    return (
      <p className="node-error" role="alert">
        {run.error_message || 'The run failed.'}
      </p>
    )
  const out = run.output ?? {}
  const made = (out.created_item_ids ?? []).flatMap((id) => items.get(id) ?? [])
  const images = made.filter((i) => i.kind !== 'note')
  const notes = made.filter((i) => i.kind === 'note')
  const skipped = Array.isArray(out.skipped_attributes) ? out.skipped_attributes.length : 0
  const text = out.text
  const nothing = made.length === 0 && text === undefined && out.table === undefined
  return (
    <>
      {images.length > 0 && (
        <ul className="node-thumbs" aria-label="Generated">
          {images.map((i) => (
            <li key={i.id}>
              <img src={itemImageUrl(i, 'thumb')} alt={itemTitle(i)} />
            </li>
          ))}
        </ul>
      )}
      {notes.length > 0 && (
        <p className="node-output-note">
          {notes.length} {notes.length === 1 ? 'note' : 'notes'} added to the board
        </p>
      )}
      {typeof text === 'string' ? (
        <p className="node-text">{text}</p>
      ) : text !== undefined && text !== null ? (
        <pre className="node-text">{JSON.stringify(text, null, 2)}</pre>
      ) : null}
      <Table value={out.table} />
      {skipped > 0 && (
        <p className="muted small">
          {skipped} {skipped === 1 ? 'attribute was' : 'attributes were'} left as they were
        </p>
      )}
      {nothing && <p className="node-output-empty">Done. Nothing new to show.</p>}
    </>
  )
}

function ParamField({ field, value, nodeId, readOnly, onSave }: { field: Field; value: unknown; nodeId: string; readOnly: boolean; onSave: (v: unknown) => void }) {
  const id = `node-${nodeId}-${field.key}`
  const initial = value === undefined ? '' : field.type === 'json' ? JSON.stringify(value) : String(value)
  const [draft, setDraft] = useState(initial)
  const [bad, setBad] = useState<string | null>(null)
  // the saved value changed (saved here, or by another tab): show it
  const [shownFor, setShownFor] = useState(initial)
  if (shownFor !== initial) {
    setShownFor(initial)
    setDraft(initial)
  }

  const commit = () => {
    if (draft === initial) return
    if (field.type === 'integer') {
      if (draft.trim() === '') return onSave(undefined)
      let n = Math.round(Number(draft))
      if (!Number.isFinite(n)) return setBad('Enter a whole number')
      if (field.min !== undefined) n = Math.max(field.min, n)
      if (field.max !== undefined) n = Math.min(field.max, n)
      setBad(null)
      setDraft(String(n))
      return onSave(n)
    }
    if (field.type === 'json') {
      if (draft.trim() === '') return onSave(undefined)
      try {
        const parsed: unknown = JSON.parse(draft)
        setBad(null)
        return onSave(parsed)
      } catch {
        return setBad('Not valid JSON')
      }
    }
    onSave(draft)
  }
  const enter = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && field.type !== 'json') {
      e.preventDefault()
      commit()
    }
  }

  let control
  if (field.type === 'enum')
    control = (
      <select id={id} value={String(value ?? '')} disabled={readOnly} onChange={(e) => onSave(e.target.value)}>
        {(field.options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    )
  else if (field.type === 'boolean')
    control = <input id={id} type="checkbox" checked={value === true} disabled={readOnly} onChange={(e) => onSave(e.target.checked)} />
  else if (field.type === 'json')
    control = (
      <textarea id={id} rows={3} value={draft} disabled={readOnly} aria-invalid={!!bad || undefined} onChange={(e) => setDraft(e.target.value)} onBlur={commit} />
    )
  else
    control = (
      <input
        id={id}
        type={field.type === 'integer' ? 'number' : 'text'}
        min={field.min}
        max={field.max}
        value={draft}
        disabled={readOnly}
        aria-invalid={!!bad || undefined}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={enter}
      />
    )
  return (
    <div className={field.type === 'boolean' ? 'node-field is-check' : 'node-field'}>
      <label htmlFor={id}>{field.label}</label>
      {control}
      {bad && <span className="node-field-bad">{bad}</span>}
    </div>
  )
}

export function NodeCard({ boardId, node, plugin, run, items, view, readOnly = false, dropTarget = false, onWheel }: Props) {
  const qc = useQueryClient()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [starting, setStarting] = useState(false)
  // 409 NODE_RUNNING: a run we have not heard of yet is going; treat the node as running until it shows up
  const [conflictFor, setConflictFor] = useState<string | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const fieldsRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const moreRef = useRef<HTMLButtonElement>(null)
  const focusField = useRef<string | null>(null)
  const drag = useRef<{ pointer: number; cx: number; cy: number; x0: number; y0: number; moved: boolean } | null>(null)

  const name = plugin?.name ?? node.plugin_id
  const fields = plugin ? paramFields(plugin.params) : []
  const values = effective(fields, node.params)
  const running = starting || (run ? ACTIVE.has(run.status) : false) || (conflictFor !== undefined && conflictFor === (run?.id ?? null))
  const check = canRun(plugin, node, items)
  const runDisabled = readOnly || running || !check.ok
  const reasonId = `node-${node.id}-reason`
  const showReason = !readOnly && !running && !check.ok && plugin?.status === 'available'
  const secondary = plugin?.secondary ?? 'Settings'

  useEffect(() => {
    if (menuOpen) menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [menuOpen])
  useEffect(() => {
    if (!settingsOpen || !fieldsRef.current) return
    const want = focusField.current
    focusField.current = null
    if (want === null) return
    const target =
      (want && fieldsRef.current.querySelector<HTMLElement>(`#node-${CSS.escape(node.id)}-${CSS.escape(want)}`)) ||
      fieldsRef.current.querySelector<HTMLElement>('input, select, textarea')
    target?.focus()
  }, [settingsOpen, node.id])

  const fail = (msg: string) => () => setError(msg)
  const saveParam = (key: string, v: unknown) => {
    const params = { ...node.params }
    if (v === undefined) delete params[key]
    else params[key] = v
    void updateNode(qc, node.id, { params }).catch(fail('Could not save the setting'))
  }

  const run_ = async () => {
    setStarting(true)
    setError(null)
    try {
      const r = await runNode(node.id)
      qc.setQueryData<NodesResponse>(keys.nodes(boardId), (old) => {
        if (!old) return old
        const cur = old.runs[node.id]
        return {
          nodes: old.nodes.map((n) => (n.id === node.id ? { ...n, last_run_id: r.id } : n)),
          runs: cur?.id === r.id ? old.runs : { ...old.runs, [node.id]: r },
        }
      })
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code === 'NODE_RUNNING') {
        setConflictFor(run?.id ?? null)
        void qc.invalidateQueries({ queryKey: keys.nodes(boardId) })
      } else setError(e instanceof ApiError ? e.message : 'Could not start the run')
    } finally {
      setStarting(false)
    }
  }

  const openSettings = (field: string) => {
    focusField.current = field
    setSettingsOpen(true)
  }

  // ---- drag by the header ----
  const onHeadDown = (e: ReactPointerEvent) => {
    if (readOnly || e.button !== 0 || (e.target as HTMLElement).closest('button')) return
    e.preventDefault()
    drag.current = { pointer: e.pointerId, cx: e.clientX, cy: e.clientY, x0: node.x, y0: node.y, moved: false }
    const at = (ev: PointerEvent, d: NonNullable<typeof drag.current>) => ({
      x: Math.round(d.x0 + (ev.clientX - d.cx) / view.scale),
      y: Math.round(d.y0 + (ev.clientY - d.cy) / view.scale),
    })
    const move = (ev: PointerEvent) => {
      const d = drag.current
      if (!d) return
      if (!d.moved && Math.hypot(ev.clientX - d.cx, ev.clientY - d.cy) < 3) return
      d.moved = true
      previewNode(qc, node.id, at(ev, d))
    }
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
      const d = drag.current
      drag.current = null
      if (!d) return
      const to = at(ev, d)
      if (!d.moved || (to.x === d.x0 && to.y === d.y0)) {
        previewNode(qc, node.id, { x: d.x0, y: d.y0 })
        return
      }
      void updateNode(qc, node.id, to, { undoable: true, before: { x: d.x0, y: d.y0 } }).catch(fail('Could not move the node'))
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
  }

  const screen = toScreenBounds(nodeBounds(node), view)
  const shown = shownFields(fields, node.params)

  return (
    <section
      className={`node-card${dropTarget ? ' is-drop' : ''}`}
      role="group"
      aria-label={`${name} node`}
      style={{ left: screen.x, top: screen.y, width: node.w, minHeight: node.h, transform: `scale(${view.scale})` }}
      onWheel={onWheel}
    >
      <div className="node-head" onPointerDown={onHeadDown} title={readOnly ? undefined : 'Drag to move'}>
        {plugin && <PluginTile plugin={plugin} size={28} />}
        <span className="node-name">{name}</span>
        {plugin && <span className="node-runs">{plugin.runs_on}</span>}
        <div className="node-more-wrap">
          <button
            ref={moreRef}
            type="button"
            className="node-more"
            aria-label="More actions"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <Dots />
          </button>
          {menuOpen && (
            <div
              ref={menuRef}
              className="node-menu"
              role="menu"
              aria-label={`${name} node`}
              onKeyDown={(e) => {
                if (e.key !== 'Escape') return
                e.stopPropagation()
                setMenuOpen(false)
                moreRef.current?.focus()
              }}
              onBlur={(e) => {
                const next = e.relatedTarget as Node | null
                if (next && !e.currentTarget.parentElement?.contains(next)) setMenuOpen(false)
              }}
            >
              <button
                type="button"
                role="menuitem"
                className="is-danger"
                disabled={readOnly}
                onClick={() => {
                  setMenuOpen(false)
                  void removeNode(qc, node.id).catch(fail('Could not remove the node'))
                }}
              >
                Remove node
              </button>
            </div>
          )}
        </div>
      </div>

      {node.input_item_ids.length > 0 ? (
        <ul className="node-chips" aria-label="Inputs">
          {node.input_item_ids.map((id) => {
            const item = items.get(id)
            return (
              <Chip
                key={id}
                item={item}
                label={inputLabel(item)}
                readOnly={readOnly}
                onRemove={() =>
                  void updateNode(qc, node.id, { input_item_ids: node.input_item_ids.filter((x) => x !== id) }, { undoable: true }).catch(
                    fail('Could not remove the input'),
                  )
                }
              />
            )
          })}
        </ul>
      ) : (
        <p className="node-hint">Drag items here, or select them before adding the node.</p>
      )}

      {plugin && (
        <div className="node-settings">
          <button
            type="button"
            className="node-summary"
            aria-expanded={settingsOpen}
            onClick={() => (settingsOpen ? setSettingsOpen(false) : openSettings(''))}
          >
            <span>{summaryLine(plugin, node.params)}</span>
            <span className="node-summary-edit" aria-hidden="true">
              {settingsOpen ? 'Done' : 'Edit'}
            </span>
          </button>
          {settingsOpen && (
            <div className="node-fields" ref={fieldsRef}>
              {shown.length === 0 && <p className="muted small">This plugin has no settings.</p>}
              {shown.map((f) => (
                <ParamField key={f.key} field={f} value={values[f.key]} nodeId={node.id} readOnly={readOnly} onSave={(v) => saveParam(f.key, v)} />
              ))}
            </div>
          )}
        </div>
      )}

      <div className="node-output">
        <Output plugin={plugin} run={run} items={items} running={running} />
      </div>

      {error && (
        <p className="node-error" role="alert">
          {error}
        </p>
      )}

      <div className="node-actions">
        <button
          type="button"
          className="node-run"
          disabled={runDisabled}
          aria-describedby={showReason ? reasonId : undefined}
          title={readOnly ? LOCKED_TITLE : !check.ok ? check.reason : undefined}
          onClick={() => void run_()}
        >
          {run && !running ? 'Run again' : 'Run'}
        </button>
        {plugin && (
          <button
            type="button"
            className="node-secondary"
            aria-expanded={settingsOpen}
            onClick={() => {
              const match = fields.find((f) => f.label.toLowerCase() === secondary.toLowerCase())
              openSettings(match?.key ?? '')
            }}
          >
            {secondary}
          </button>
        )}
      </div>
      {showReason && (
        <p className="node-reason" id={reasonId}>
          {check.reason}
        </p>
      )}
    </section>
  )
}
