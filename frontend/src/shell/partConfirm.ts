/** A part the agent asks the person to confirm: its item framed on the board, the part's mask and box drawn. */
import { useSyncExternalStore } from 'react'
import type { AgentAnswer } from '../api'

export interface PartConfirm {
  /** The question's call: a drawn box answers it. */
  callId: string
  itemId: string
  /** The part's mask, an app path like `/api/media/masks/….png`. */
  maskUrl: string | null
  /** The part's box, [x0, y0, x1, y1] as fractions of the item. */
  box: number[] | null
  /** `draw`: a drag over the item draws a new box. */
  mode: 'show' | 'draw'
  /** Sends the person's answer (a drawn box). */
  answer: (answer: AgentAnswer) => void
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

export const partConfirmStore = createStore<PartConfirm | null>(null)

export const usePartConfirm = (): PartConfirm | null =>
  useSyncExternalStore(partConfirmStore.subscribe, partConfirmStore.get)

/** Switches the shown confirmation between showing the part and drawing a box. */
export function setConfirmMode(mode: PartConfirm['mode']): void {
  const cur = partConfirmStore.get()
  if (cur && cur.mode !== mode) partConfirmStore.set({ ...cur, mode })
}

/** Ends the confirmation for this call (another call's is left alone). */
export function clearPartConfirm(callId: string): void {
  if (partConfirmStore.get()?.callId === callId) partConfirmStore.set(null)
}
