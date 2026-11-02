import { afterEach, describe, expect, it, vi } from 'vitest'
import { isCollapsed, setCollapsed, subscribeCollapsed } from './collapse'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('collapse', () => {
  it('collapse persists per board in localStorage and survives storage throwing', () => {
    expect(isCollapsed('b1', 'e1')).toBe(false) // default
    setCollapsed('b1', 'e1', true)
    expect(isCollapsed('b1', 'e1')).toBe(true)
    expect(isCollapsed('b2', 'e1')).toBe(false) // per board
    expect(JSON.parse(localStorage.getItem('muse.flowers.collapsed.b1')!)).toEqual(['e1'])
    setCollapsed('b1', 'e1', false)
    expect(isCollapsed('b1', 'e1')).toBe(false)
    expect(JSON.parse(localStorage.getItem('muse.flowers.collapsed.b1')!)).toEqual([])

    // storage blocked (private window, cleared site data): nothing throws, the default holds
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(isCollapsed('b3', 'e9')).toBe(false)
    expect(() => setCollapsed('b3', 'e9', true)).not.toThrow()
    // still collapsed for this session
    expect(isCollapsed('b3', 'e9')).toBe(true)
  })

  it('ignores junk in storage', () => {
    localStorage.setItem('muse.flowers.collapsed.b1', '{not json')
    expect(isCollapsed('b1', 'e1')).toBe(false)
    localStorage.setItem('muse.flowers.collapsed.b1', '{"e1": true}')
    expect(isCollapsed('b1', 'e1')).toBe(false)
  })

  it('tells subscribers when a flower collapses or opens', () => {
    const l = vi.fn()
    const off = subscribeCollapsed(l)
    setCollapsed('b1', 'e1', true)
    expect(l).toHaveBeenCalledTimes(1)
    off()
    setCollapsed('b1', 'e1', false)
    expect(l).toHaveBeenCalledTimes(1)
  })
})
