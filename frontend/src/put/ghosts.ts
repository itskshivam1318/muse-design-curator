import { useSyncExternalStore } from 'react'
import type { putInto } from '../api'

/** A placeholder shown on the board while a put-into job runs (client only). */
export interface Ghost {
  jobId: string
  boardId: string
  targetId: string
  x: number
  y: number
  w: number
  h: number
  /** What was asked, kept so a failed ghost can try again. */
  request: { targetId: string; body: Parameters<typeof putInto>[1] }
  error: string | null
}

let ghosts: readonly Ghost[] = []
const listeners = new Set<() => void>()
const set = (next: readonly Ghost[]) => {
  ghosts = next
  listeners.forEach((l) => l())
}

export const ghostStore = {
  get: () => ({ ghosts }),
  forBoard: (boardId: string) => ghosts.filter((g) => g.boardId === boardId),
  subscribe(l: () => void) {
    listeners.add(l)
    return () => listeners.delete(l)
  },
}

/** Jobs that settled before their ghost was added (null = done, string = failure message); bounded. */
const settled = new Map<string, string | null>()
const SETTLED_MAX = 50
function remember(jobId: string, outcome: string | null): void {
  settled.delete(jobId)
  settled.set(jobId, outcome)
  if (settled.size > SETTLED_MAX) settled.delete(settled.keys().next().value as string)
}

export function addGhost(g: Ghost): void {
  if (settled.has(g.jobId)) {
    const outcome = settled.get(g.jobId)!
    if (outcome === null) return
    set([...ghosts, { ...g, error: outcome }])
    return
  }
  set([...ghosts, g])
}

export function failGhost(jobId: string, message: string): void {
  if (!ghosts.some((g) => g.jobId === jobId)) {
    remember(jobId, message)
    return
  }
  set(ghosts.map((g) => (g.jobId === jobId ? { ...g, error: message } : g)))
}

export function removeGhost(jobId: string): void {
  if (!ghosts.some((g) => g.jobId === jobId)) {
    remember(jobId, null)
    return
  }
  set(ghosts.filter((g) => g.jobId !== jobId))
}

export function useGhosts(boardId: string): Ghost[] {
  const all = useSyncExternalStore(ghostStore.subscribe, () => ghosts)
  return all.filter((g) => g.boardId === boardId)
}
