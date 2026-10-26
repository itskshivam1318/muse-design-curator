/** Undo stack for position changes only (⌘Z). */
import type { Point } from '../api'

export interface Move {
  id: string
  from: Point
  to: Point
}

const LIMIT = 50

export function createMoveHistory() {
  const stack: Move[][] = []
  return {
    push(moves: Move[]) {
      const real = moves.filter((m) => m.from.x !== m.to.x || m.from.y !== m.to.y)
      if (real.length === 0) return
      stack.push(real)
      if (stack.length > LIMIT) stack.shift()
    },
    /** The moves to revert, newest first; null when there is nothing to undo. */
    pop(): Move[] | null {
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

export type MoveHistory = ReturnType<typeof createMoveHistory>
