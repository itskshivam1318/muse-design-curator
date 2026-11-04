import { describe, expect, it } from 'vitest'
import { exp, opt } from '../test/explore'
import { makeItem } from '../test/fixtures'
import { changedPassage, notesBeingWritten, pendingNotes } from './noteTakes'

const note = makeItem({ id: 'n', kind: 'note', note_text: 'Hook 1.' })
const take = (id: string, over = {}) => makeItem({ id, kind: 'note', staged: true, note_text: 'Hook 1, hotel.', ...over })
const picture = makeItem({ id: 'p', kind: 'image' })

describe('pendingNotes', () => {
  it('lists the staged takes of a note exploration that are neither dismissed nor kept', () => {
    const items = [note, take('t1'), take('t2'), take('t3')]
    const e = exp('e1', 'domain', [
      opt('o1', { takes: ['t1'] }),
      opt('o2', { takes: ['t2'], status: 'dismissed' }),
      opt('o3', { takes: ['t3'], kept_item_id: 't3', status: 'kept' }),
    ], 'n')
    const got = pendingNotes(items, [e])
    expect([...got.keys()]).toEqual(['t1'])
    expect(got.get('t1')?.option.id).toBe('o1')
  })

  it('ignores explorations grown from a picture (those keep their flower)', () => {
    const items = [picture, take('t1')]
    expect(pendingNotes(items, [exp('e1', 'mood', [opt('o1', { takes: ['t1'] })], 'p')]).size).toBe(0)
  })

  it('ignores a take already on the board', () => {
    const items = [note, take('t1', { staged: false })]
    expect(pendingNotes(items, [exp('e1', 'domain', [opt('o1', { takes: ['t1'] })], 'n')]).size).toBe(0)
  })
})

describe('notesBeingWritten', () => {
  it('counts the note options still being written', () => {
    const e = exp('e1', 'domain', [opt('o1', { status: 'visualizing' }), opt('o2', { status: 'visualizing' }), opt('o3')], 'n')
    expect(notesBeingWritten([note], [e]).get('n')).toBe(2)
    expect(notesBeingWritten([picture], [exp('e2', 'mood', [opt('o1', { status: 'visualizing' })], 'p')]).size).toBe(0)
  })
})

describe('changedPassage', () => {
  it('marks a changed passage, not a whole rewrite', () => {
    expect(changedPassage(take('t', { note_text: 'Aaa. BBB. Ccc.', generation: { changed_range: [5, 9] } }))).toEqual([5, 9])
    expect(changedPassage(take('t', { note_text: 'QUIET', generation: { changed_range: [0, 5] } }))).toBeNull()
    expect(changedPassage(take('t', { generation: null }))).toBeNull()
  })
})
