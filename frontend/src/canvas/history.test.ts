import { describe, expect, it } from 'vitest'
import { createMoveHistory } from './history'

describe('move history', () => {
  it('ignores no-op moves and undoes the last batch', () => {
    const h = createMoveHistory()
    h.push([{ id: 'a', from: { x: 0, y: 0 }, to: { x: 0, y: 0 } }])
    expect(h.size).toBe(0)
    h.push([{ id: 'a', from: { x: 0, y: 0 }, to: { x: 5, y: 5 } }])
    h.push([{ id: 'b', from: { x: 1, y: 1 }, to: { x: 2, y: 2 } }])
    expect(h.pop()?.[0].id).toBe('b')
    expect(h.pop()?.[0].id).toBe('a')
    expect(h.pop()).toBeNull()
  })
})
