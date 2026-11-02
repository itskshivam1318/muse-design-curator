import { describe, expect, it } from 'vitest'
import { FEEL } from './physics'
import { dockedSize, ellipsePoint, PETAL, petalAngles, petalRadius, ringAngles, undockedSize } from './ring'

const gap = (a: number, b: number) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)))

describe('ring geometry', () => {
  it('ringAngles spreads anchors that all sit below the item', () => {
    const owner = { w: 300, h: 200 }
    const angles = ringAngles(owner, [-80, -40, 0, 40, 80].map((x) => ({ x, y: 90 })))
    expect(angles).toHaveLength(5)
    for (let i = 0; i < 5; i++) for (let j = i + 1; j < 5; j++) expect(gap(angles[i], angles[j])).toBeGreaterThanOrEqual((2 * Math.PI) / 5 - 1e-6)
  })

  it('ringAngles keeps a single right anchor at angle 0', () => {
    const [a] = ringAngles({ w: 200, h: 150 }, [{ x: 70, y: 0 }])
    expect(gap(a, 0)).toBeCloseTo(0)
  })

  it('ringAngles puts a whole-item anchor below', () => {
    const [a] = ringAngles({ w: 200, h: 150 }, [null])
    expect(gap(a, Math.PI / 2)).toBeCloseTo(0)
  })

  it('ellipsePoint clears the owner by the gap along each axis', () => {
    expect(ellipsePoint({ w: 200, h: 150 }, 0, { x: 105, y: 46 })).toEqual({ x: 205, y: 0 })
    const below = ellipsePoint({ w: 200, h: 150 }, Math.PI / 2, { x: 105, y: 46 })
    expect(below.x).toBeCloseTo(0)
    expect(below.y).toBeCloseTo(121)
  })

  it('petalAngles spans the arc around the direction', () => {
    expect(petalAngles(1, 3)).toEqual([1 - 2.35, 1, 1 + 2.35])
    expect(petalAngles(1, 1)).toEqual([1])
  })

  it('dockedSize keeps the aspect at 168 wide', () => {
    expect(dockedSize({ w: 400, h: 250 })).toEqual({ w: 168, h: 105 })
    expect(undockedSize({ w: 168, h: 105 })).toEqual({ w: 300, h: 187.5 })
  })

  it('neighbouring petal slots are at least a petal + gap apart for n = 2..12', () => {
    for (let n = 2; n <= 12; n++) {
      const R = petalRadius(n)
      const [a, b] = petalAngles(0, n)
      const chord = Math.hypot(Math.cos(a) * R - Math.cos(b) * R, Math.sin(a) * R - Math.sin(b) * R)
      expect(chord, `n = ${n}`).toBeGreaterThanOrEqual(PETAL + FEEL.gap - 1e-9)
      expect(R).toBeGreaterThanOrEqual(135)
    }
  })
})
