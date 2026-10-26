/** Board server-sent events: keeps the React Query cache in step with the server. */
import type { QueryClient } from '@tanstack/react-query'
import { API_ORIGIN, type Item, keys, type ProfileSnapshot } from './api'

export const EVENT_TYPES = [
  'item.added',
  'item.parsed',
  'item.failed',
  'item.updated',
  'item.removed',
  'profile.updated',
  'lens.proposed',
  'run.progress',
  'run.completed',
] as const

export type BoardEventType = (typeof EVENT_TYPES)[number]

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

/** Apply one event to the cache. Pure with respect to the network: it never fetches. */
export function applyEvent(qc: QueryClient, boardId: string, type: string, data: unknown): void {
  const d = (data ?? {}) as Record<string, unknown>
  switch (type) {
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
      if (everOpened) {
        // events may have been missed while we were away: refetch what the stream maintains
        void qc.invalidateQueries({ queryKey: keys.items(boardId) })
        void qc.invalidateQueries({ queryKey: keys.lens(boardId) })
      }
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
