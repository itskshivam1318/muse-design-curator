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

export interface RailState {
  /** The open left-rail panel, if any (BoardPage closes it in its Escape chain). */
  open: RailId | null
  /** Who opened it: the person (the panel takes focus) or the board (it leaves focus be). */
  reason: 'user' | 'auto'
  /** A lens proposal waits in Library while another panel is open (a dot on the Library icon). */
  lensWaiting: boolean
}

export const railStore = createStore<RailState>({ open: null, reason: 'user', lensWaiting: false })
export const useRail = (): RailState => useSyncExternalStore(railStore.subscribe, railStore.get)

export function openRail(id: RailId, reason: RailState['reason'] = 'user'): void {
  const cur = railStore.get()
  railStore.set({ open: id, reason, lensWaiting: id === 'library' ? false : cur.lensWaiting })
}

export function closeRail(): void {
  const cur = railStore.get()
  if (cur.open !== null) railStore.set({ ...cur, open: null })
}

/** A lens proposal appeared (or went): open Library for it, or flag Library if another panel is open. */
export function noteLensProposal(present: boolean): void {
  const cur = railStore.get()
  if (!present) {
    if (cur.lensWaiting) railStore.set({ ...cur, lensWaiting: false })
  } else if (cur.open === null) openRail('library', 'auto')
  else if (cur.open !== 'library') railStore.set({ ...cur, lensWaiting: true })
}

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
