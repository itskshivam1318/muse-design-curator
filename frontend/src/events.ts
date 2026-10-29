/** Board server-sent events: keeps the React Query cache in step with the server. */
import type { QueryClient } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import {
  API_ORIGIN,
  type Board,
  type Exploration,
  type Item,
  keys,
  type NodesResponse,
  type PluginInfo,
  type PluginRun,
  type ProfileSnapshot,
} from './api'

export const EVENT_TYPES = [
  'item.added',
  'item.parsed',
  'item.failed',
  'item.updated',
  'item.removed',
  'profile.updated',
  'board.updated',
  'lens.proposed',
  'explore.updated',
  'run.progress',
  'run.completed',
  'note.visualizing',
  'note.visualized',
  'note.visualize_failed',
  'plugin_run.queued',
  'plugin_run.progress',
  'plugin_run.done',
  'plugin_run.failed',
] as const

export type BoardEventType = (typeof EVENT_TYPES)[number]

type Listener = () => void

function createStore<S>(initial: S) {
  let state = initial
  const listeners = new Set<Listener>()
  return {
    get: () => state,
    set(next: S) {
      state = next
      listeners.forEach((l) => l())
    },
    subscribe(l: Listener) {
      listeners.add(l)
      return () => listeners.delete(l)
    },
  }
}

/** Notes whose image is being made right now (note ids; ids are unique across boards). */
export const noteVisualizeStore = createStore<{ ids: ReadonlySet<string> }>({ ids: new Set() })

export const useNoteVisualizing = (noteId: string): boolean =>
  useSyncExternalStore(noteVisualizeStore.subscribe, () => noteVisualizeStore.get().ids.has(noteId))

/** Mark a note as visualizing (or not); the click sets it ahead of the server's note.visualizing. */
export function setVisualizing(noteId: string, on: boolean): void {
  const ids = new Set(noteVisualizeStore.get().ids)
  if (on === ids.has(noteId)) return
  if (on) ids.add(noteId)
  else ids.delete(noteId)
  noteVisualizeStore.set({ ids })
}

/** The server frees a note's visualize claim after this long (its job died); matches CLAIM_TTL_S. */
export const VISUALIZE_CLAIM_TTL_MS = 300_000

/**
 * Loaded items: each note is visualizing exactly when the server holds a fresh visualize claim on
 * it (after a reload mid-visualize the note.visualizing event is long gone; a refetch after a
 * missed note.visualized clears it). Returns the items unchanged.
 */
export function seedVisualizing(items: Item[], now = Date.now()): Item[] {
  for (const i of items) {
    if (i.kind !== 'note') continue
    const since = i.generation?.visualizing_since
    const at = since ? Date.parse(since) : NaN
    setVisualizing(i.id, Number.isFinite(at) && now - at < VISUALIZE_CLAIM_TTL_MS)
  }
  return items
}

export interface ActivityEntry {
  at: string
  text: string
}
const ACTIVITY_MAX = 50

const activityStore = createStore<{ entries: readonly ActivityEntry[] }>({ entries: [] })

/** The last 50 things that happened on the board, oldest first, as plain sentences. */
export const boardActivity = {
  get: activityStore.get,
  subscribe: activityStore.subscribe,
  push(text: string) {
    const entries = [...activityStore.get().entries, { at: new Date().toISOString(), text }]
    activityStore.set({ entries: entries.slice(-ACTIVITY_MAX) })
  },
  clear() {
    activityStore.set({ entries: [] })
  },
}

export const useBoardActivity = (): readonly ActivityEntry[] =>
  useSyncExternalStore(boardActivity.subscribe, () => boardActivity.get().entries).slice()

export interface DescribeContext {
  pluginName?: string
  noteLabel?: string
  /** The kind of a board item by id, from the cache; undefined when it is not there yet. */
  itemKind?: (id: string) => Item['kind'] | undefined
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** "4 images", "1 note", "2 images and 1 note"; "3 items" when any kind is unknown. */
function madeText(ids: readonly string[], itemKind: DescribeContext['itemKind']): string {
  const kinds = ids.map((id) => itemKind?.(id))
  if (kinds.some((k) => k === undefined)) return `${plural(ids.length, 'item')} added`
  const images = kinds.filter((k) => k !== 'note').length
  const notes = kinds.length - images
  const parts = [images ? plural(images, 'image') : '', notes ? plural(notes, 'note') : ''].filter(Boolean)
  return `${parts.join(' and ')} added`
}

const VISUALIZE_ERRORS: Record<string, string> = {
  IMAGE_MODEL_FAILED: 'the image model failed',
  INTERRUPTED: 'it was interrupted',
  MODEL_TIMEOUT: 'the image model took too long',
  MODEL_UNAVAILABLE: 'the image model is unavailable',
  MODEL_RATE_LIMITED: 'the image model is busy, try again shortly',
  MODEL_API_KEY: 'the image model key is missing or invalid',
  MODEL_INVALID_RESPONSE: 'the image model sent back something unusable',
  VISUALIZE_ERROR: 'something went wrong',
}

/** A visualize failure code in plain words. */
export const visualizeErrorText = (code: string): string => VISUALIZE_ERRORS[code] ?? 'something went wrong'

/** A plain sentence for an event worth telling the person about; null for the rest. */
export function describeEvent(type: string, data: unknown, ctx: DescribeContext = {}): string | null {
  const d = (data ?? {}) as Record<string, unknown>
  const plugin = ctx.pluginName ?? 'Plugin'
  switch (type) {
    case 'plugin_run.queued':
      return `${plugin} is running`
    case 'plugin_run.done': {
      const made = (d.output as PluginRun['output'] | undefined)?.created_item_ids ?? []
      return made.length > 0 ? `${plugin} finished: ${madeText(made, ctx.itemKind)}` : `${plugin} finished`
    }
    case 'plugin_run.failed':
      return typeof d.error_message === 'string' && d.error_message
        ? `${plugin} failed: ${d.error_message}`
        : `${plugin} failed`
    case 'note.visualizing':
      return 'Visualizing note'
    case 'note.visualized':
      return `${ctx.noteLabel ?? 'Note'} visualized`
    case 'note.visualize_failed':
      return typeof d.error === 'string' && d.error
        ? `${ctx.noteLabel ?? 'Note'} could not be visualized: ${visualizeErrorText(d.error)}`
        : `${ctx.noteLabel ?? 'Note'} could not be visualized`
  }
  return null
}

function upsert(items: Item[] | undefined, item: Item): Item[] {
  const list = items ?? []
  const at = list.findIndex((i) => i.id === item.id)
  if (at === -1) return [...list, item]
  const next = list.slice()
  next[at] = { ...list[at], ...item }
  return next
}

function patch(items: Item[] | undefined, id: string, fields: Partial<Item>): Item[] | undefined {
  if (!items) return items
  return items.map((i) => (i.id === id ? { ...i, ...fields } : i))
}

export function upsertItems(qc: QueryClient, boardId: string, added: Item[]): void {
  qc.setQueryData<Item[]>(keys.items(boardId), (old) => added.reduce(upsert, old ?? []))
}

const RUN_STATUS: Record<string, PluginRun['status']> = {
  'plugin_run.queued': 'queued',
  'plugin_run.progress': 'running',
  'plugin_run.done': 'done',
  'plugin_run.failed': 'failed',
}

function applyRunEvent(qc: QueryClient, boardId: string, type: string, d: Record<string, unknown>): void {
  const nodeId = String(d.node_id)
  const runId = String(d.run_id)
  let stale = false
  qc.setQueryData<NodesResponse>(keys.nodes(boardId), (old) => {
    if (!old) return old
    const node = old.nodes.find((n) => n.id === nodeId)
    const cur = old.runs[nodeId]
    // a late event of an older run must not overwrite the node's newer one
    if (cur && cur.id !== runId && node?.last_run_id === cur.id && type !== 'plugin_run.queued') {
      stale = true
      return old
    }
    const base: PluginRun = cur?.id === runId ? cur : {
      id: runId, node_id: nodeId, plugin_id: node?.plugin_id ?? '', status: 'queued', progress: null,
      output: null, error_code: null, error_message: null, created_at: new Date().toISOString(),
      finished_at: null,
    }  // prettier-ignore
    const status = RUN_STATUS[type]
    const next: PluginRun = { ...base, status }
    if (type === 'plugin_run.progress') next.progress = (d.progress as PluginRun['progress']) ?? base.progress
    if (type === 'plugin_run.done') {
      next.progress = null
      next.output = (d.output as PluginRun['output']) ?? null
      next.finished_at = new Date().toISOString()
    }
    if (type === 'plugin_run.failed') {
      next.progress = null
      next.error_code = (d.error_code as string | undefined) ?? null
      next.error_message = (d.error_message as string | undefined) ?? null
      next.finished_at = new Date().toISOString()
    }
    return {
      nodes: old.nodes.map((n) => (n.id === nodeId ? { ...n, last_run_id: runId } : n)),
      runs: { ...old.runs, [nodeId]: next },
    }
  })
  // not the run we hold: refetch instead of dropping what the server knows
  if (stale) void qc.invalidateQueries({ queryKey: keys.nodes(boardId) })
}

function noteLabel(qc: QueryClient, boardId: string, noteId: unknown): string | undefined {
  const text = qc.getQueryData<Item[]>(keys.items(boardId))?.find((i) => i.id === noteId)?.note_text?.trim()
  if (!text) return undefined
  return text.length > 40 ? `${text.slice(0, 40).trimEnd()}...` : text
}

function pluginName(qc: QueryClient, boardId: string, nodeId: unknown): string | undefined {
  const nodes = qc.getQueryData<NodesResponse>(keys.nodes(boardId))?.nodes
  const pluginId = nodes?.find((n) => n.id === nodeId)?.plugin_id
  return qc.getQueryData<PluginInfo[]>(keys.plugins())?.find((p) => p.id === pluginId)?.name
}

/** Apply one event to the cache. Pure with respect to the network: it never fetches. */
export function applyEvent(qc: QueryClient, boardId: string, type: string, data: unknown): void {
  const d = (data ?? {}) as Record<string, unknown>
  applyToCache(qc, boardId, type, d)
  const text = describeEvent(type, d, {
    pluginName: pluginName(qc, boardId, d.node_id),
    noteLabel: noteLabel(qc, boardId, d.note_id),
    itemKind: (id) => qc.getQueryData<Item[]>(keys.items(boardId))?.find((i) => i.id === id)?.kind,
  })
  if (text) boardActivity.push(text)
}

function applyToCache(qc: QueryClient, boardId: string, type: string, d: Record<string, unknown>): void {
  switch (type) {
    case 'note.visualizing':
      setVisualizing(String(d.note_id), true)
      return
    case 'note.visualized':
    case 'note.visualize_failed':
      setVisualizing(String(d.note_id), false)
      return
    case 'plugin_run.queued':
    case 'plugin_run.progress':
    case 'plugin_run.done':
    case 'plugin_run.failed':
      applyRunEvent(qc, boardId, type, d)
      return
    case 'item.added':
    case 'item.updated': {
      const item = d as unknown as Item
      if (item.board_id && item.board_id !== boardId) return
      qc.setQueryData<Item[]>(keys.items(boardId), (old) => upsert(old, item))
      return
    }
    case 'item.parsed':
      void qc.invalidateQueries({ queryKey: keys.attributes(String(d.item_id)) })
      qc.setQueryData<Item[]>(keys.items(boardId), (old) =>
        patch(old, String(d.item_id), {
          parse_status: d.parse_status as Item['parse_status'],
          parse_error_code: null,
        }),
      )
      return
    case 'item.failed':
      qc.setQueryData<Item[]>(keys.items(boardId), (old) =>
        patch(old, String(d.item_id), {
          parse_status: 'failed',
          parse_error_code: (d.error_code as string | undefined) ?? null,
        }),
      )
      return
    case 'item.removed':
      qc.setQueryData<Item[]>(keys.items(boardId), (old) => old?.filter((i) => i.id !== d.id))
      return
    case 'profile.updated': {
      const snap = d as unknown as ProfileSnapshot
      qc.setQueryData<ProfileSnapshot>(keys.profile(boardId), (old) =>
        old && old.version > snap.version ? old : snap,
      )
      return
    }
    case 'board.updated': {
      // the server changed the board itself (e.g. an Auto board chose its domain and lens)
      const board = d.board as Board | undefined
      if (!board || board.id !== boardId) return
      qc.setQueryData<Board>(keys.board(boardId), (old) => ({ ...old, ...board }))
      void qc.invalidateQueries({ queryKey: keys.lens(boardId) })
      // a grown vocabulary changes every item's attribute options
      void qc.invalidateQueries({ queryKey: ['attributes'] })
      return
    }
    case 'explore.updated': {
      const e = d as unknown as Exploration
      if (!e.id || e.board_id !== boardId) return
      qc.setQueryData<Exploration[]>(keys.explorations(boardId), (old) => {
        const list = old ?? []
        const at = list.findIndex((x) => x.id === e.id)
        if (at === -1) return [...list, e]
        const next = list.slice()
        next[at] = e
        return next
      })
      return
    }
    case 'lens.proposed':
      void qc.invalidateQueries({ queryKey: keys.lens(boardId) })
      void qc.invalidateQueries({ queryKey: keys.board(boardId) })
      return
    case 'run.progress':
    case 'run.completed':
      if (typeof d.run_id === 'string') void qc.invalidateQueries({ queryKey: keys.run(d.run_id) })
      return
  }
}

export interface ConnectOptions {
  /** Called for every event after the cache is updated. */
  onEvent?: (type: BoardEventType, data: unknown) => void
  onStatus?: (status: 'open' | 'reconnecting') => void
  makeSource?: (url: string) => EventSource
}

const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000, 30000]

/** Subscribe to a board's stream. Reconnects with backoff and resyncs on reconnect. */
export function connectBoardEvents(
  boardId: string,
  qc: QueryClient,
  opts: ConnectOptions = {},
): () => void {
  const url = `${API_ORIGIN}/api/boards/${encodeURIComponent(boardId)}/events`
  boardActivity.clear() // activity belongs to the board being watched
  const make = opts.makeSource ?? ((u: string) => new EventSource(u))
  let source: EventSource | null = null
  let attempt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false
  let everOpened = false

  const open = () => {
    if (closed) return
    source = make(url)
    source.onopen = () => {
      opts.onStatus?.('open')
      // events may have been missed before the stream opened (a job that ended between the page's
      // items fetch and now) or while we were away: refetch the items every time it opens
      void qc.invalidateQueries({ queryKey: keys.items(boardId) })
      if (everOpened) void qc.invalidateQueries({ queryKey: keys.lens(boardId) })
      everOpened = true
      attempt = 0
    }
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (ev) => {
        let data: unknown = null
        try {
          data = JSON.parse((ev as MessageEvent<string>).data)
        } catch {
          return
        }
        applyEvent(qc, boardId, type, data)
        opts.onEvent?.(type, data)
      })
    }
    source.onerror = () => {
      source?.close()
      source = null
      if (closed) return
      opts.onStatus?.('reconnecting')
      const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
      attempt += 1
      timer = setTimeout(open, wait)
    }
  }

  open()
  return () => {
    closed = true
    if (timer) clearTimeout(timer)
    source?.close()
  }
}
