/** Board tools (select / note) and which rail panel is open: small shared stores. */
import { useSyncExternalStore } from 'react'

export type Tool = 'select' | 'note'
export type RailId = 'library' | 'search' | 'plugins' | 'vocabulary'

export const RAIL_LABELS: Record<RailId, string> = {
  library: 'Library',
  search: 'Search',
  plugins: 'Plugins',
  vocabulary: 'Vocabulary',
}

type Listener = () => void

function createStore<S>(initial: S) {
  let state = initial
  const listeners = new Set<Listener>()
  return {
    get: () => state,
    set(next: S) {
      if (Object.is(next, state)) return
      state = next
      listeners.forEach((l) => l())
    },
    subscribe(l: Listener) {
      listeners.add(l)
      return () => {
        listeners.delete(l)
      }
    },
  }
}

export const toolStore = createStore<Tool>('select')
export const setTool = (t: Tool): void => toolStore.set(t)
export const useTool = (): Tool => useSyncExternalStore(toolStore.subscribe, toolStore.get)

export interface RailState {
  /** The open left-rail panel, if any (BoardPage closes it in its Escape chain). */
  open: RailId | null
  /** Who opened it: the person (the panel takes focus) or the board (it leaves focus be). */
  reason: 'user' | 'auto'
}

export const railStore = createStore<RailState>({ open: null, reason: 'user' })
export const useRail = (): RailState => useSyncExternalStore(railStore.subscribe, railStore.get)

export function openRail(id: RailId, reason: RailState['reason'] = 'user'): void {
  railStore.set({ open: id, reason })
}

export function closeRail(): void {
  const cur = railStore.get()
  if (cur.open !== null) railStore.set({ ...cur, open: null })
}

/** `n` note, `Escape` select; every other key is not a tool key. */
export function toolForKey(key: string): Tool | null {
  if (key === 'Escape') return 'select'
  switch (key.toLowerCase()) {
    case 'n':
      return 'note'
    default:
      return null
  }
}
