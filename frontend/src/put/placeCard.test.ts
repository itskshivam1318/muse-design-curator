import { describe, expect, it } from 'vitest'
import { placeCard, type Rect } from './placeCard'

const card = { w: 260, h: 170 }
const viewport = { w: 1000, h: 700 }
const overlaps = (a: Rect, b: Rect) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top

describe('placeCard', () => {
  it('opens right-below the drop when it fits', () => {
    expect(placeCard({ x: 100, y: 100 }, card, viewport, [])).toEqual({ x: 100, y: 100 })
  })

  it('keeps the card inside the viewport', () => {
    const p = placeCard({ x: 950, y: 690 }, card, viewport, [])
    expect(p.x).toBeGreaterThanOrEqual(16)
    expect(p.y).toBeGreaterThanOrEqual(16)
    expect(p.x + card.w).toBeLessThanOrEqual(viewport.w - 16)
    expect(p.y + card.h).toBeLessThanOrEqual(viewport.h - 16)
  })

  it('clamps when no corner fits', () => {
    const p = placeCard({ x: 500, y: 300 }, { w: 980, h: 690 }, viewport, [])
    expect(p).toEqual({ x: 16, y: 16 })
  })

  it('avoids the agent card', () => {
    const agent: Rect = { left: 644, top: 524, right: 984, bottom: 684 }
    const p = placeCard({ x: 700, y: 560 }, card, viewport, [agent])
    const r: Rect = { left: p.x, top: p.y, right: p.x + card.w, bottom: p.y + card.h }
    expect(overlaps(r, agent)).toBe(false)
    expect(r.right).toBeLessThanOrEqual(viewport.w - 16)
    expect(r.bottom).toBeLessThanOrEqual(viewport.h - 16)
  })
})
