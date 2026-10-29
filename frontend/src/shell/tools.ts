/** Board tools (select / note / axis) and which rail panel is open: small shared stores. */
import { useSyncExternalStore } from 'react'

export type Tool = 'select' | 'note' | 'axis'
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

/** The open left-rail panel, if any (BoardPage closes it in its Escape chain). */
export const railStore = createStore<RailId | null>(null)
export const useRail = (): RailId | null => useSyncExternalStore(railStore.subscribe, railStore.get)

/** `n` note, `a` axis (only with explore on), `Escape` select; every other key is not a tool key. */
export function toolForKey(key: string, flags: { explore: boolean }): Tool | null {
  if (key === 'Escape') return 'select'
  switch (key.toLowerCase()) {
    case 'n':
      return 'note'
    case 'a':
      return flags.explore ? 'axis' : null
    default:
      return null
  }
}
