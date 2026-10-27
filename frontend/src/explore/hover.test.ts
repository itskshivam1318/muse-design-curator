import { afterEach, describe, expect, it, vi } from 'vitest'
import { hoverStore, setHoveredOption } from './hover'

describe('hover store', () => {
  afterEach(() => setHoveredOption(null))

  it('notifies subscribers and holds the hovered option id', () => {
    const l = vi.fn()
    const off = hoverStore.subscribe(l)
    setHoveredOption('opt_1')
    expect(hoverStore.get()).toBe('opt_1')
    expect(l).toHaveBeenCalledTimes(1)
    setHoveredOption('opt_1') // unchanged: no churn
    expect(l).toHaveBeenCalledTimes(1)
    setHoveredOption(null)
    expect(hoverStore.get()).toBeNull()
    expect(l).toHaveBeenCalledTimes(2)
    off()
    setHoveredOption('opt_2')
    expect(l).toHaveBeenCalledTimes(2)
  })
})
