/** Undo stack (⌘Z) for position changes and explore-option edits (note moves, dismisses). */
import type { Point } from '../api'

export interface Move {
  id: string
  from: Point
  to: Point
}

/** Item moves are reverted by the item actions; anything else carries its own revert. */
export type UndoEntry = { kind: 'moves'; moves: Move[] } | { kind: 'revert'; revert: () => void }

const LIMIT = 50

export function createUndoHistory() {
  const stack: UndoEntry[] = []
  const add = (entry: UndoEntry) => {
    stack.push(entry)
    if (stack.length > LIMIT) stack.shift()
  }
  return {
    push(moves: Move[]) {
      const real = moves.filter((m) => m.from.x !== m.to.x || m.from.y !== m.to.y)
      if (real.length > 0) add({ kind: 'moves', moves: real })
    },
    pushRevert(revert: () => void) {
      add({ kind: 'revert', revert })
    },
    /** The newest entry to undo; null when there is nothing to undo. */
    pop(): UndoEntry | null {
      return stack.pop() ?? null
    },
    get size() {
      return stack.length
    },
    clear() {
      stack.length = 0
    },
  }
}

export type UndoHistory = ReturnType<typeof createUndoHistory>

/**
 * The open board's undo stack, shared by the canvas and the drawer so ⌘Z undoes the newest
 * change wherever it was made. useItemActions clears it when the board changes.
 */
export const undoHistory = createUndoHistory()
