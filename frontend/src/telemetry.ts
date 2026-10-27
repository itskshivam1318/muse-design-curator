/**
 * Board UI events (what the person did: opened Vary, ran it, opened a candidate, closed the strip).
 * Runs and decisions already record outcomes on the server; this records the path to them, so a
 * confusing moment can be traced afterwards (GET /api/boards/{id}/ui-events).
 *
 * Fire-and-forget: events are batched, posted with keepalive, and never surface an error.
 */
import { API_ORIGIN } from './api'

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
  if (id !== boardId) flush()
  boardId = id
}

export function track(
  action: string,
  fields: { itemId?: string | null; runId?: string | null; detail?: Record<string, unknown> } = {},
): void {
  if (!boardId) return
  if (queue.length >= MAX_QUEUE) queue.shift()
  queue.push({
    action,
    ...(fields.itemId ? { item_id: fields.itemId } : {}),
    ...(fields.runId ? { run_id: fields.runId } : {}),
    ...(fields.detail ? { detail: fields.detail } : {}),
    at: new Date().toISOString(),
  })
  if (queue.length >= MAX_BATCH) flush()
  else if (!timer) timer = setTimeout(flush, FLUSH_MS)
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flush)
  document.addEventListener('visibilitychange', () => document.visibilityState === 'hidden' && flush())
}
