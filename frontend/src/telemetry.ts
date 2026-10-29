/**
 * Board UI events (what the person did: opened Vary, ran it, opened a candidate, closed the strip).
 * Runs and decisions already record outcomes on the server; this records the path to them, so a
 * confusing moment can be traced afterwards (GET /api/boards/{id}/ui-events).
 *
 * Fire-and-forget: events are batched, posted with keepalive, and never surface an error.
 */
import { useSyncExternalStore } from 'react'
import { API_ORIGIN } from './api'
import { humanize } from './format'

export interface UiEvent {
  action: string
  item_id?: string | null
  run_id?: string | null
  detail?: Record<string, unknown>
  at: string
}

const FLUSH_MS = 2000
const MAX_BATCH = 50
const MAX_QUEUE = 500

let boardId: string | null = null
let queue: UiEvent[] = []
let timer: ReturnType<typeof setTimeout> | null = null

function post(board: string, events: UiEvent[]): void {
  try {
    void fetch(`${API_ORIGIN}/api/boards/${encodeURIComponent(board)}/ui-events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events }),
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    /* logging must never break the board */
  }
}

export function flush(): void {
  if (timer) clearTimeout(timer)
  timer = null
  if (!boardId || !queue.length) return
  const board = boardId
  const all = queue
  queue = []
  for (let i = 0; i < all.length; i += MAX_BATCH) post(board, all.slice(i, i + MAX_BATCH))
}

/** The board events belong to; switching boards flushes what the previous one queued. */
export function setBoard(id: string | null): void {
  if (id !== boardId) {
    flush()
    clearActivity()
  }
  boardId = id
}

// ---- what the person did, as sentences for the agent card (in memory, last 50) ----

export interface UiActivityEntry {
  at: string
  text: string
}
const ACTIVITY_MAX = 50
const PANEL_NAMES: Record<string, string> = {
  inspect: 'Inspect',
  explore: 'Explore',
  vary: 'Find real examples',
  compare: 'Compare',
}
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`
const count = (detail: Record<string, unknown> | undefined) =>
  Array.isArray(detail?.items) ? detail.items.length : 1

/** A plain sentence for a UI action worth showing; null for noisy or unknown ones. */
export function describeUiAction(action: string, detail: Record<string, unknown> | undefined): string | null {
  switch (action) {
    case 'drawer.open': {
      const name = PANEL_NAMES[String(detail?.kind)]
      return name ? `Opened ${name}.` : null
    }
    case 'vary.run': {
      const target = typeof detail?.target === 'string' ? humanize(detail.target).toLowerCase() : null
      return target ? `Started Find real examples for ${target}.` : 'Started Find real examples.'
    }
    case 'candidate.keep':
      return 'Kept a real example.'
    case 'candidate.reject':
      return 'Rejected a real example.'
    case 'item.remove':
      return `Removed ${plural(count(detail), 'item')}.`
    case 'item.role': {
      const n = plural(count(detail), 'item')
      return detail?.role === 'reference' ? `Moved ${n} back to references.` : `Marked ${n} as not this.`
    }
    default:
      return null
  }
}

let activity: readonly UiActivityEntry[] = []
const activityListeners = new Set<() => void>()
const notify = () => activityListeners.forEach((l) => l())

function clearActivity(): void {
  if (!activity.length) return
  activity = []
  notify()
}

/** The last 50 described UI actions on the open board, oldest first. */
export const uiActivity = {
  get: (): readonly UiActivityEntry[] => activity,
  subscribe(l: () => void) {
    activityListeners.add(l)
    return () => {
      activityListeners.delete(l)
    }
  },
}

export const useUiActivity = (): readonly UiActivityEntry[] => useSyncExternalStore(uiActivity.subscribe, uiActivity.get)

export function track(
  action: string,
  fields: { itemId?: string | null; runId?: string | null; detail?: Record<string, unknown> } = {},
): void {
  if (!boardId) return
  if (queue.length >= MAX_QUEUE) queue.shift()
  const at = new Date().toISOString()
  queue.push({
    action,
    ...(fields.itemId ? { item_id: fields.itemId } : {}),
    ...(fields.runId ? { run_id: fields.runId } : {}),
    ...(fields.detail ? { detail: fields.detail } : {}),
    at,
  })
  const text = describeUiAction(action, fields.detail)
  if (text) {
    activity = [...activity, { at, text }].slice(-ACTIVITY_MAX)
    notify()
  }
  if (queue.length >= MAX_BATCH) flush()
  else if (!timer) timer = setTimeout(flush, FLUSH_MS)
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flush)
  document.addEventListener('visibilitychange', () => document.visibilityState === 'hidden' && flush())
}
