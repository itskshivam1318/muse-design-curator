/** The explore option under the pointer, shared by the drawer list and the canvas notes. */
import { useSyncExternalStore } from 'react'

type Listener = () => void

let hovered: string | null = null
const listeners = new Set<Listener>()

export const hoverStore = {
  get: () => hovered,
  subscribe(l: Listener) {
    listeners.add(l)
    return () => listeners.delete(l)
  },
}

export function setHoveredOption(id: string | null): void {
  if (id === hovered) return
  hovered = id
  listeners.forEach((l) => l())
}

export function useHoveredOption(): string | null {
  return useSyncExternalStore(hoverStore.subscribe, hoverStore.get)
}
