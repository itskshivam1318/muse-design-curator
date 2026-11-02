import { describe, expect, it } from 'vitest'
import { makeAttrs } from '../test/attrs'
import { chipSource } from './source'

describe('chipSource', () => {
  const base = makeAttrs().attributes[0]
  it('maps attribute provenance onto the six marks', () => {
    expect(chipSource({ ...base, measured: { lab: [1, 2, 3] } })).toBe('measured')
    expect(chipSource(base)).toBe('read')
    expect(chipSource({ ...base, status: 'uncertain' })).toBe('estimated')
    expect(chipSource({ ...base, source: 'web' })).toBe('web')
    expect(chipSource({ ...base, source: 'user' })).toBe('you')
    expect(chipSource({ ...base, status: 'confirmed' })).toBe('you')
    expect(chipSource({ ...base, status: 'missing', value: null })).toBe('unknown')
  })
})
