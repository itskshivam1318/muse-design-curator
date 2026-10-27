import { describe, expect, it } from 'vitest'
import type { AttributeSpec, ExploreOption } from '../api'
import { canFindReal, findRealRequest, optionTree } from './logic'

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: over.id, description: '',
    distance: 'near', value: over.id, keeps: [], status: 'open', last_error: null, x: null, y: null,
    created_at: '2026-10-28T00:00:00Z', ...over,
  }
}

const FINISH: AttributeSpec = { key: 'case_finish', label: 'Case finish', category: 'case', kind: 'enum', vocabulary: ['brushed', 'polished'] }

describe('optionTree', () => {
  it('optionTree nests branches', () => {
    const options = [
      opt({ id: 'c', batch: 2, created_at: '2026-10-28T00:00:03Z' }),
      opt({ id: 'a1', batch: 3, parent_option_id: 'a', created_at: '2026-10-28T00:00:05Z' }),
      opt({ id: 'b', batch: 1, created_at: '2026-10-28T00:00:02Z' }),
      opt({ id: 'a', batch: 1, created_at: '2026-10-28T00:00:01Z' }),
      opt({ id: 'a1x', batch: 4, parent_option_id: 'a1', created_at: '2026-10-28T00:00:06Z' }),
    ]
    expect(optionTree(options).map((r) => [r.option.id, r.depth])).toEqual([
      ['a', 0], ['a1', 1], ['a1x', 2], ['b', 0], ['c', 0],
    ])
  })

  it('optionTree drops dismissed', () => {
    const options = [opt({ id: 'a' }), opt({ id: 'b', status: 'dismissed' }), opt({ id: 'c', status: 'visualized' })]
    expect(optionTree(options).map((r) => r.option.id)).toEqual(['a', 'c'])
  })
})

describe('canFindReal', () => {
  it('canFindReal closed enum outside vocab false', () => {
    expect(canFindReal(FINISH, 'sandblasted')).toBe(false)
    expect(canFindReal(FINISH, null)).toBe(false)
    expect(canFindReal(FINISH, 'brushed')).toBe(true)
  })

  it('canFindReal after vocab update true', () => {
    const grown = { ...FINISH, vocabulary: ['brushed', 'polished', 'sandblasted'] }
    expect(canFindReal(grown, 'sandblasted')).toBe(true)
    expect(canFindReal({ ...FINISH, open_vocabulary: true }, 'anything')).toBe(true)
    expect(canFindReal({ key: 'd', label: 'D', category: 'x', kind: 'boolean' }, false)).toBe(true)
  })
})

describe('findRealRequest', () => {
  it('findRealRequest maps keeps', () => {
    const o = opt({ id: 'o1', value: 'sandblasted', keeps: ['dial_color', 'legibility'] })
    expect(findRealRequest('i1', 'case_finish', o)).toEqual({
      source_item_id: 'i1',
      target_key: 'case_finish',
      mode: 'prefer',
      target_values: ['sandblasted'],
      protected_keys: ['dial_color', 'legibility'],
      nudge: null,
    })
  })
})
