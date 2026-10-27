import { describe, expect, it, vi } from 'vitest'
import { createUndoHistory } from './history'

describe('undo history', () => {
  it('ignores no-op moves and undoes the last batch', () => {
    const h = createUndoHistory()
    h.push([{ id: 'a', from: { x: 0, y: 0 }, to: { x: 0, y: 0 } }])
    expect(h.size).toBe(0)
    h.push([{ id: 'a', from: { x: 0, y: 0 }, to: { x: 5, y: 5 } }])
    h.push([{ id: 'b', from: { x: 1, y: 1 }, to: { x: 2, y: 2 } }])
    const b = h.pop()
    expect(b?.kind === 'moves' && b.moves[0].id).toBe('b')
    const a = h.pop()
    expect(a?.kind === 'moves' && a.moves[0].id).toBe('a')
    expect(h.pop()).toBeNull()
  })

  it('keeps item moves and other reverts (note moves, dismisses) in one newest-first stack', () => {
    const h = createUndoHistory()
    const revert = vi.fn()
    h.push([{ id: 'a', from: { x: 0, y: 0 }, to: { x: 5, y: 5 } }])
    h.pushRevert(revert)
    expect(h.size).toBe(2)
    expect(h.pop()).toEqual({ kind: 'revert', revert })
    expect(h.pop()?.kind).toBe('moves')
  })
})
