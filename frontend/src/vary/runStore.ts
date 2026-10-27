/** The board's active variation run (one at a time), shared by VaryPanel and the Maybe strip. */
import { useSyncExternalStore } from 'react'
import type { VariationRequest } from '../api'
import { track } from '../telemetry'

export interface ActiveRun {
  boardId: string
  runId: string
  request: VariationRequest
}

export interface RunState {
  active: ActiveRun | null
  /** Candidate whose popover is open. */
  openCandidate: string | null
}

let state: RunState = { active: null, openCandidate: null }
const listeners = new Set<() => void>()
const set = (next: Partial<RunState>) => {
  state = { ...state, ...next }
  listeners.forEach((l) => l())
}

export const runStore = {
  get: () => state,
  subscribe(l: () => void) {
    listeners.add(l)
    return () => listeners.delete(l)
  },
  start(active: ActiveRun) {
    set({ active, openCandidate: null })
  },
  open(candidateId: string | null) {
    const runId = state.active?.runId
    if (candidateId) track('candidate.open', { runId, detail: { candidate: candidateId } })
    else if (state.openCandidate) track('candidate.close', { runId, detail: { candidate: state.openCandidate } })
    set({ openCandidate: candidateId })
  },
  clear() {
    if (state.active) track('run.dismiss', { runId: state.active.runId, itemId: state.active.request.source_item_id })
    set({ active: null, openCandidate: null })
  },
}

export function useRunState(): RunState {
  return useSyncExternalStore(runStore.subscribe, runStore.get)
}
