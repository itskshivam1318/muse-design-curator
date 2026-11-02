import { describe, expect, it } from 'vitest'
import type { ItemAttribute } from './api'
import { colorHex, compareDiff, formatValue } from './attrValues'

function attr(key: string, value: ItemAttribute['value'], over: Partial<ItemAttribute> = {}): ItemAttribute {
  return {
    key, label: key.replace(/_/g, ' '), category: 'c', kind: 'enum', part: null, value,
    confidence: 0.9, status: 'extracted', source: 'model', enabled: true, ...over,
  }
}

describe('values', () => {
  it('formats values for display', () => {
    expect(formatValue('royal_blue')).toBe('royal blue')
    expect(formatValue(40, 'mm')).toBe('40 mm')
    expect(formatValue(true)).toBe('yes')
    expect(formatValue(null)).toBe('unknown')
  })

  it('finds a colour hex from the measured hex, a hex value or a named colour', () => {
    expect(colorHex('navy', { hex: '#123456' })).toBe('#123456')
    expect(colorHex('#abcdef')).toBe('#abcdef')
    expect(colorHex('navy')).toBe('#000080')
    expect(colorHex('nope')).toBeNull()
  })
})

describe('compare', () => {
  it('compare shows only differing attributes', () => {
    const rows = compareDiff([
      { itemId: 'i1', attributes: [attr('a', 'x'), attr('b', 'same'), attr('c', 3, { kind: 'number' })] },
      { itemId: 'i2', attributes: [attr('a', 'y'), attr('b', 'same'), attr('c', 3, { kind: 'number' })] },
      { itemId: 'i3', attributes: [attr('a', 'x'), attr('b', 'same')] },
    ])
    expect(rows.map((r) => r.key)).toEqual(['a', 'c'])
    expect(rows[0].values).toEqual(['x', 'y', 'x'])
    expect(rows[1].values).toEqual([3, 3, null])
  })
})
