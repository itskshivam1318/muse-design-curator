/**
 * Which flowers are collapsed to a badge, per board, kept in this browser's localStorage
 * (`muse.flowers.collapsed.<boardId>`: a JSON list of exploration ids). Storage can be missing or
 * throw (private window, blocked site data): reads then fall back to this session's memory and
 * default to open; writes never throw.
 */

type Listener = () => void

const key = (boardId: string) => `muse.flowers.collapsed.${boardId}`
const memory = new Map<string, Set<string>>()
const listeners = new Set<Listener>()
let version = 0

function read(boardId: string): Set<string> {
  try {
    const raw = localStorage.getItem(key(boardId))
    if (raw === null) return memory.get(boardId) ?? new Set()
    const ids: unknown = JSON.parse(raw)
    return new Set(Array.isArray(ids) ? ids.filter((x): x is string => typeof x === 'string') : [])
  } catch {
    return memory.get(boardId) ?? new Set()
  }
}

export function isCollapsed(boardId: string, id: string): boolean {
  return read(boardId).has(id)
}

export function setCollapsed(boardId: string, id: string, value: boolean): void {
  const ids = read(boardId)
  if (value) ids.add(id)
  else ids.delete(id)
  memory.set(boardId, ids)
  try {
    localStorage.setItem(key(boardId), JSON.stringify([...ids]))
  } catch {
    // kept in memory for this session
  }
  version++
  listeners.forEach((l) => l())
}

export function subscribeCollapsed(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Bumps on every change (a useSyncExternalStore snapshot). */
export const collapsedVersion = (): number => version
