import { describe, expect, it } from 'vitest'
import { mergeActivity } from './activity'

describe('mergeActivity', () => {
  it('merges both streams by time, oldest first', () => {
    const server = [
      { at: '2026-10-29T10:00:00.000Z', text: 'A' },
      { at: '2026-10-29T10:02:00.000Z', text: 'C' },
    ]
    const ui = [{ at: '2026-10-29T10:01:00.000Z', text: 'B' }, { at: '2026-10-29T10:03:00.000Z', text: 'D' }]
    expect(mergeActivity(server, ui).map((e) => e.text)).toEqual(['A', 'B', 'C', 'D'])
  })
})
