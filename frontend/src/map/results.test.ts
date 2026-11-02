import { describe, expect, it } from 'vitest'
import type { ExploreOption } from '../api'
import { makeItem } from '../test/fixtures'
import { changeExcerpt, resultOf } from './results'

describe('changeExcerpt', () => {
  it('marks only the changed span, with context', () => {
    expect(changeExcerpt('The quick brown fox', 'The quick red fox')).toEqual({ pre: 'The quick ', mark: 'red', post: ' fox' })
    const long = 'a'.repeat(100)
    const x = changeExcerpt(`${long}OLD${long}`, `${long}NEW${long}`, 5)
    expect(x).toEqual({ pre: '…aaaaa', mark: 'NEW', post: 'aaaaa…' })
  })
})

describe('resultOf', () => {
  const o = (over: Partial<ExploreOption>) => ({ kept_item_id: null, takes: [], ...over }) as unknown as ExploreOption
  it('is the kept item, else the newest take that has arrived', () => {
    const byId = new Map([['t1', makeItem({ id: 't1' })], ['k', makeItem({ id: 'k' })]])
    expect(resultOf(o({ takes: ['t1', 't2'] }), byId)?.id).toBe('t1')
    expect(resultOf(o({ takes: ['t1'], kept_item_id: 'k' }), byId)?.id).toBe('k')
    expect(resultOf(o({}), byId)).toBeUndefined()
  })
})
