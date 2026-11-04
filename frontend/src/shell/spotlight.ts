/** Spotlight replay: a finished run's highlighted steps, played one at a time over the board. */
import { useSyncExternalStore } from 'react'
import type { AgentStep } from '../api'

export interface Spotlight {
  runId: string
  steps: AgentStep[]
  index: number
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

/** The steps a replay plays: highlighted and successful, in turn order. */
export function replaySteps(steps: AgentStep[]): AgentStep[] {
  return steps.filter((s) => s.highlight && s.ok).sort((a, b) => a.turn - b.turn)
}

export const spotlightStore = createStore<Spotlight | null>(null)

export const useSpotlight = (): Spotlight | null =>
  useSyncExternalStore(spotlightStore.subscribe, spotlightStore.get)

export function startSpotlight(runId: string, steps: AgentStep[]): void {
  const playable = replaySteps(steps)
  if (playable.length === 0) return
  spotlightStore.set({ runId, steps: playable, index: 0 })
}

/** Advances one step; past the last step the replay closes. */
export function nextSpot(): void {
  const cur = spotlightStore.get()
  if (cur === null) return
  if (cur.index + 1 >= cur.steps.length) {
    closeSpotlight()
    return
  }
  spotlightStore.set({ ...cur, index: cur.index + 1 })
}

/** Goes back one step, not below the first. */
export function backSpot(): void {
  const cur = spotlightStore.get()
  if (cur === null || cur.index === 0) return
  spotlightStore.set({ ...cur, index: cur.index - 1 })
}

export function closeSpotlight(): void {
  spotlightStore.set(null)
}

export function currentStep(s: Spotlight | null): AgentStep | null {
  return s?.steps[s.index] ?? null
}
