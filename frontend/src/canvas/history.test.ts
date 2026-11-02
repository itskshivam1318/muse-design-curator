import { describe, expect, it, vi } from 'vitest'
import { createUndoHistory } from './history'

describe('undo history', () => {
  it('undoes the newest revert first', () => {
    const h = createUndoHistory()
    const a = vi.fn()
    const b = vi.fn()
    h.pushRevert(a)
    h.pushRevert(b)
    expect(h.size).toBe(2)
    expect(h.pop()).toEqual({ kind: 'revert', revert: b })
    expect(h.pop()).toEqual({ kind: 'revert', revert: a })
    expect(h.pop()).toBeNull()
  })
})
