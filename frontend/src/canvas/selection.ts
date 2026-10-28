/**
 * Selection and drawer state shared by the canvas, toolbar and side panels.
 * Extension point: Inspect / Vary panels (Task 18) read `drawer` and register themselves
 * with `registerDrawerPanel` in panels/RightDrawer.tsx.
 */
import { useSyncExternalStore } from 'react'
import { track } from '../telemetry'

export interface DrawerState {
  kind: string
  itemId: string
  /** Panel-specific options, e.g. Vary's preset target or Compare's item ids. */
  params?: Record<string, unknown>
}

export interface SelectionState {
  selected: readonly string[]
  drawer: DrawerState | null
}

type Listener = () => void

function createStore(initial: SelectionState) {
  let state = initial
  const listeners = new Set<Listener>()
  return {
    get: () => state,
    set(next: Partial<SelectionState>) {
      state = { ...state, ...next }
      listeners.forEach((l) => l())
    },
    subscribe(l: Listener) {
      listeners.add(l)
      return () => listeners.delete(l)
    },
  }
}

export const selectionStore = createStore({ selected: [], drawer: null })

export const selection = {
  select(ids: readonly string[]) {
    selectionStore.set({ selected: [...new Set(ids)] })
  },
  toggle(id: string) {
    const cur = selectionStore.get().selected
    selectionStore.set({ selected: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] })
  },
  add(ids: readonly string[]) {
    selectionStore.set({ selected: [...new Set([...selectionStore.get().selected, ...ids])] })
  },
  clear() {
    selectionStore.set({ selected: [] })
  },
  /** Drop ids that no longer exist (e.g. after item.removed). */
  retain(existing: ReadonlySet<string>) {
    const cur = selectionStore.get().selected
    if (cur.some((id) => !existing.has(id))) selectionStore.set({ selected: cur.filter((id) => existing.has(id)) })
    const d = selectionStore.get().drawer
    if (d && !existing.has(d.itemId)) selectionStore.set({ drawer: null })
  },
  openDrawer(kind: string, itemId: string, params?: Record<string, unknown>) {
    track('drawer.open', { itemId, detail: { kind } })
    selectionStore.set({ drawer: { kind, itemId, ...(params ? { params } : {}) } })
  },
  closeDrawer() {
    const d = selectionStore.get().drawer
    if (d) track('drawer.close', { itemId: d.itemId, detail: { kind: d.kind } })
    selectionStore.set({ drawer: null })
  },
  reset() {
    selectionStore.set({ selected: [], drawer: null })
  },
}

export function useSelection(): SelectionState {
  return useSyncExternalStore(selectionStore.subscribe, selectionStore.get)
}
