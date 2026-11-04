import { describe, expect, it } from 'vitest'
import { makeMessage, makeStep } from '../../test/fixtures'
import { textParts, threadEntries } from './thread'

describe('threadEntries', () => {
  it('threadEntries orders by time', () => {
    const ask = makeMessage({ id: 'm1', role: 'person', created_at: '2026-11-04T10:00:00Z' })
    const reply = makeMessage({ id: 'm2', role: 'agent', created_at: '2026-11-04T10:00:03Z' })
    const look = makeStep({ id: 's1', created_at: '2026-11-04T10:00:01Z' })
    const act = makeStep({ id: 's2', turn: 2, created_at: '2026-11-04T10:00:02Z' })
    const entries = threadEntries([reply, ask], [act, look])
    expect(entries.map((e) => (e.kind === 'message' ? e.message.id : e.step.id))).toEqual(['m1', 's1', 's2', 'm2'])
  })

  it('puts a message before a step at the same moment', () => {
    const at = '2026-11-04T10:00:00Z'
    const entries = threadEntries([makeMessage({ created_at: at })], [makeStep({ created_at: at })])
    expect(entries.map((e) => e.kind)).toEqual(['message', 'step'])
  })
})

describe('textParts', () => {
  it('splits item ids out of the text', () => {
    expect(textParts('Try itm_1 next to itm_ab2.')).toEqual([
      { text: 'Try ' },
      { itemId: 'itm_1' },
      { text: ' next to ' },
      { itemId: 'itm_ab2' },
      { text: '.' },
    ])
  })

  it('keeps plain text whole', () => {
    expect(textParts('No pictures here')).toEqual([{ text: 'No pictures here' }])
  })
})
