import { describe, expect, it } from 'vitest'
import type { PartView } from '../api'
import { analysis } from '../test/explore'
import { aimAt, headNoun, partAt, sameKind, spotLabel, toBody, type Spot } from './spots'

const part = (key: string, label: string, region: number[] | null, region_kind: PartView['region_kind'] = 'box'): PartView => ({
  key, label, region_kind, region, mask_url: null, source: 'ai',
})
const front = part('fw', 'Front wheel', [0, 0.6, 0.3, 1])
const body = part('body', 'Car body', [0, 0.2, 1, 0.9])
const rear = part('rw', 'Rear wheel', [0.7, 0.6, 1, 1])

describe('headNoun', () => {
  it('takes the last word, lower-cased, singular', () => {
    expect(headNoun('Front wheel')).toBe('wheel')
    expect(headNoun('Rear Wheels')).toBe('wheel')
    expect(headNoun('Glass')).toBe('glass')
  })
})

describe('partAt', () => {
  it('picks the smaller of two overlapping boxes', () => {
    expect(partAt([body, front], 0.1, 0.7)).toBe(front)
  })
  it('ignores parts without a box', () => {
    expect(partAt([part('x', 'X', null), part('t', 'T', [0, 5], 'text_range')], 0.5, 0.5)).toBeNull()
  })
})

describe('sameKind', () => {
  it('puts the aimed part first, then its kind in order', () => {
    expect(sameKind([front, body, rear], rear)).toEqual([rear, front])
  })
})

describe('aimAt', () => {
  it('falls back to a point without an analysis', () => {
    expect(aimAt(undefined, 0.3, 0.4)).toEqual([{ kind: 'point', fx: 0.3, fy: 0.4 }])
    expect(aimAt(null, 0.3, 0.4)).toEqual([{ kind: 'point', fx: 0.3, fy: 0.4 }])
  })
  it('falls back to a point off every part', () => {
    expect(aimAt(analysis, 0.1, 0.1)).toEqual([{ kind: 'point', fx: 0.1, fy: 0.1 }])
  })
  it('returns the part under the point and its kind', () => {
    const a = { ...analysis, parts: [front, body, rear] }
    expect(aimAt(a, 0.8, 0.8)).toEqual([
      { kind: 'part', part: rear },
      { kind: 'part', part: front },
    ])
  })
})

describe('toBody', () => {
  const spots: Spot[] = [{ kind: 'part', part: front }, { kind: 'point', fx: 0.5, fy: 0.5 }, { kind: 'part', part: rear }]
  it('drops switched-off spots and maps the rest', () => {
    expect(toBody(spots, new Set([0]))).toEqual([{ point: { fx: 0.5, fy: 0.5 } }, { part: 'rw' }])
  })
})

describe('spotLabel', () => {
  it('names the part or says Here', () => {
    expect(spotLabel({ kind: 'part', part: front })).toBe('Front wheel')
    expect(spotLabel({ kind: 'point', fx: 0, fy: 0 })).toBe('Here')
  })
})
