import { describe, expect, it } from 'vitest'
import { fitView, toScreenBounds } from './geometry'

describe('fitView', () => {
  it('fits all items inside the viewport minus insets, never zooming past 100%', () => {
    const items = [
      { x: 0, y: 0, width: 1000, height: 500 },
      { x: 1500, y: 800, width: 500, height: 500 },
    ]
    const insets = { top: 100, right: 300, bottom: 50, left: 50 }
    const v = fitView(items, { width: 1350, height: 850 }, insets)
    const a = toScreenBounds({ x: 0, y: 0, width: 2000, height: 1300 }, v)
    expect(a.x).toBeGreaterThanOrEqual(50 - 1e-9)
    expect(a.y).toBeGreaterThanOrEqual(100 - 1e-9)
    expect(a.x + a.width).toBeLessThanOrEqual(1350 - 300 + 1e-9)
    expect(a.y + a.height).toBeLessThanOrEqual(850 - 50 + 1e-9)
    expect(fitView([{ x: 0, y: 0, width: 10, height: 10 }], { width: 800, height: 600 }).scale).toBe(1)
  })
})
