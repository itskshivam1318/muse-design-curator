import { describe, expect, it } from 'vitest'
import { rectsIntersect } from '../canvas/geometry'
import { clampCard, placeBeside } from './layout'

describe('placeBeside', () => {
  it('puts the box just outside the anchor along dir when the way is clear', () => {
    const petal = { x: 0, y: 0, width: 88, height: 88 }
    const b = placeBeside(petal, 0, { width: 200, height: 150 }, [petal])
    expect(b.x).toBeGreaterThan(petal.x + petal.width)
    expect(b.y + b.height / 2).toBeCloseTo(44)
  })

  it('steps around obstacles and never overlaps one', () => {
    const petal = { x: 0, y: 0, width: 88, height: 88 }
    const wall = { x: 100, y: -400, width: 300, height: 900 }
    const b = placeBeside(petal, 0, { width: 200, height: 150 }, [petal, wall])
    expect(rectsIntersect(b, wall)).toBe(false)
    expect(rectsIntersect(b, petal)).toBe(false)
    // deterministic
    expect(placeBeside(petal, 0, { width: 200, height: 150 }, [petal, wall])).toEqual(b)
  })
})

describe('clampCard', () => {
  const size = { width: 260, height: 300 }
  const area = { width: 1200, height: 800 }
  const agent = { x: 844, y: 584, width: 340, height: 200 } // bottom-right, 16px in

  it('leaves a card that fits where it is', () => {
    expect(clampCard({ x: 100, y: 100 }, size, area, agent)).toEqual({ x: 100, y: 100 })
  })

  it('pulls a card back inside the area, keeping the margin', () => {
    expect(clampCard({ x: 1100, y: -50 }, size, area, null)).toEqual({ x: 1200 - 8 - 260, y: 8 })
    expect(clampCard({ x: -40, y: 700 }, size, area, null)).toEqual({ x: 8, y: 800 - 8 - 300 })
  })

  it('moves a card off the agent card by the shorter way: left of it or above it', () => {
    // near its left edge: moving left is shorter
    expect(clampCard({ x: 700, y: 450 }, size, area, agent)).toEqual({ x: 844 - 8 - 260, y: 450 })
    // over its middle, near its top: moving up is shorter
    const tall = { width: 260, height: 100 }
    expect(clampCard({ x: 900, y: 560 }, tall, area, agent)).toEqual({ x: 900, y: 584 - 8 - 100 })
  })

  it('a card that cannot clear the agent card upward goes left of it', () => {
    const tall = { width: 260, height: 700 }
    const p = clampCard({ x: 900, y: 0 }, tall, area, agent)
    expect(p).toEqual({ x: 844 - 8 - 260, y: 8 })
  })

  it('keeps clear of several rects in turn (the agent card and the selection toolbar)', () => {
    const toolbar = { x: 100, y: 100, width: 200, height: 40 }
    const agent = { x: 0, y: 300, width: 400, height: 100 }
    const p = clampCard({ x: 120, y: 110 }, { width: 100, height: 80 }, { width: 800, height: 600 }, [agent, toolbar])
    const box = { ...p, width: 100, height: 80 }
    expect(rectsIntersect(box, toolbar)).toBe(false)
    expect(rectsIntersect(box, agent)).toBe(false)
  })
})
