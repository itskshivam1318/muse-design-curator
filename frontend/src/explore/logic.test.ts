import { describe, expect, it } from 'vitest'
import type { ExploreOption } from '../api'
import { optionTree } from './logic'

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: over.id, description: '',
    distance: 'near', value: over.id, keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null,
    created_at: '2026-10-28T00:00:00Z', ...over,
  }
}


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

