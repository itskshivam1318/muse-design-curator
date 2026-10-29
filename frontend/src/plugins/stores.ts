/** Small shared state between the canvas's node layer and the plugin UI outside it. */
import { useSyncExternalStore } from 'react'
import type { Point } from '../api'
import { toCanvasPoint, type View } from '../canvas/geometry'

function createStore<T>(initial: T) {
  let state = initial
  const listeners = new Set<() => void>()
  return {
    get: () => state,
    set(next: T) {
      if (Object.is(next, state)) return
      state = next
      listeners.forEach((l) => l())
    },
    subscribe(l: () => void) {
      listeners.add(l)
      return () => listeners.delete(l)
    },
  }
}

/** The canvas view and size, published by the node layer, so the Nodes menu can place a node in view. */
export const viewportStore = createStore<{ view: View; width: number; height: number } | null>(null)

/** The canvas point at the middle of the viewport (origin before the canvas has measured). */
export function viewportCenter(): Point {
  const v = viewportStore.get()
  return v ? toCanvasPoint({ x: v.width / 2, y: v.height / 2 }, v.view) : { x: 0, y: 0 }
}

/** The node an item drag is over (it takes the items as inputs on release). */
export const dropTargetStore = createStore<string | null>(null)
export const useDropTarget = () => useSyncExternalStore(dropTargetStore.subscribe, dropTargetStore.get)

/** A plugin action that failed outside a card (e.g. Send to node), shown by the node layer. */
export const nodeNoticeStore = createStore<string | null>(null)
export const useNodeNotice = () => useSyncExternalStore(nodeNoticeStore.subscribe, nodeNoticeStore.get)
