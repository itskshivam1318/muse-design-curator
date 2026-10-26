import { describe, expect, it } from 'vitest'
import { makeItem } from '../test/fixtures'
import { handleRects, hoverOutlineRect, imageNodeProps, statusDot } from './nodeProps'

describe('imageNodeProps', () => {
  it('image node has strokeWidth 0 and cornerRadius 0', () => {
    const p = imageNodeProps(makeItem({ x: 5, y: 6, w: 120, h: 80 }))
    expect(p.strokeWidth).toBe(0)
    expect(p.cornerRadius).toBe(0)
    expect(p.shadowEnabled).toBe(false)
    expect(p.strokeEnabled).toBe(false)
    // no padding: the node is exactly the item's bounds
    expect([p.x, p.y, p.width, p.height]).toEqual([5, 6, 120, 80])
  })
})

describe('hoverOutlineRect', () => {
  it('hover outline is offset outside bounds', () => {
    const b = { x: 100, y: 50, width: 200, height: 100 }
    const r = hoverOutlineRect(b, 1)
    expect(r.x).toBe(96)
    expect(r.y).toBe(46)
    expect(r.width).toBe(208)
    expect(r.height).toBe(108)
    expect(r.strokeWidth).toBe(1)
    expect(r.fillEnabled).toBe(false)
    // the stroke's inner edge never touches the image
    expect(r.x + r.strokeWidth / 2).toBeLessThan(b.x)
    expect(r.x + r.width - r.strokeWidth / 2).toBeGreaterThan(b.x + b.width)
  })

  it('keeps a constant 4 px screen gap and 1 px line under zoom', () => {
    const r = hoverOutlineRect({ x: 0, y: 0, width: 10, height: 10 }, 2)
    expect(r.x).toBe(-2)
    expect(r.strokeWidth).toBe(0.5)
  })
})

describe('status dot and handles', () => {
  it('dot sits outside the top-left corner, 8 px across', () => {
    const d = statusDot({ x: 100, y: 100, width: 50, height: 50 }, 1)
    expect(d.radius * 2).toBe(8)
    expect(d.x + d.radius).toBeLessThan(100)
    expect(d.y + d.radius).toBeLessThan(100)
  })

  it('dot clears the top-left handle when the item is selected', () => {
    const b = { x: 100, y: 100, width: 50, height: 50 }
    const d = statusDot(b, 1, true)
    const tl = handleRects(b, 1)[0]
    expect(d.x + d.radius).toBeLessThanOrEqual(tl.x)
    expect(d.y + d.radius).toBeLessThanOrEqual(tl.y)
  })

  it('four corner handles lie fully outside the image', () => {
    const b = { x: 0, y: 0, width: 100, height: 100 }
    const hs = handleRects(b, 1)
    expect(hs).toHaveLength(4)
    for (const h of hs) {
      const inside =
        h.x < b.x + b.width && h.x + h.width > b.x && h.y < b.y + b.height && h.y + h.height > b.y
      expect(inside).toBe(false)
    }
  })
})
