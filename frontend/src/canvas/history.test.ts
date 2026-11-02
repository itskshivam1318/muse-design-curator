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

  it('drops one entry by its revert, leaving the rest', () => {
    const h = createUndoHistory()
    const a = vi.fn()
    const b = vi.fn()
    h.pushRevert(a)
    h.pushRevert(b)
    h.drop(a)
    h.drop(vi.fn()) // not there: nothing happens
    expect(h.size).toBe(1)
    expect(h.pop()).toEqual({ kind: 'revert', revert: b })
  })
})
