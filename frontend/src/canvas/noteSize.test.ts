import { describe, expect, it } from 'vitest'
import { makeItem } from '../test/fixtures'
import { NOTE_MIN_H, NOTE_W, sizedNote } from './noteSize'

describe('sizedNote', () => {
  it('draws a note at the note width, its height from its text', () => {
    const n = sizedNote(makeItem({ id: 'n', kind: 'note', note_text: 'hi', w: 400, h: 10 }))
    expect([n.w, n.h]).toEqual([NOTE_W, NOTE_MIN_H])
  })

  it('a note take keeps its stored width (docked small, undocked wide), its height in proportion', () => {
    const docked = sizedNote(makeItem({ id: 't', kind: 'note', note_text: 'hi', explore_option_id: 'o1', w: 168, h: 10 }))
    expect([docked.w, docked.h]).toEqual([168, (NOTE_MIN_H * 168) / NOTE_W])
  })

  it('leaves other items alone', () => {
    const i = makeItem({ id: 'i', w: 300, h: 200 })
    expect(sizedNote(i)).toBe(i)
  })
})
