import { describe, expect, it } from 'vitest'
import type { Exploration, ExploreOption } from '../api'
import { makeItem } from '../test/fixtures'
import { fanPositions, NOTE_H, NOTE_W, noteLines, notePlacement, placedNotes } from './notes'
import { lineagePoints } from './nodeProps'

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`,
    description: '', distance: 'near', value: 'v', keeps: [], status: 'open', last_error: null,
    x: null, y: null, created_at: `2026-10-28T00:00:0${over.id.slice(-1)}Z`, ...over,
  }
}

const exploration = (options: ExploreOption[], over: Partial<Exploration> = {}): Exploration => ({
  id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options, ...over,
})

const source = makeItem({ id: 'src', x: 0, y: 0, w: 200, h: 150 })
const srcBounds = { x: 0, y: 0, width: 200, height: 150 }

describe('note layout', () => {
  it('fanPositions column right of source', () => {
    const ps = fanPositions(srcBounds, 3, 0)
    expect(ps.map((p) => p.x)).toEqual([260, 260, 260])
    // three notes and two gaps, centred on the source's middle (75)
    const top = 75 - (3 * NOTE_H + 2 * 16) / 2
    expect(ps.map((p) => p.y)).toEqual([top, top + NOTE_H + 16, top + 2 * (NOTE_H + 16)])
  })

  it('fanPositions wraps after 6', () => {
    const ps = fanPositions(srcBounds, 8, 0)
    expect(ps.slice(0, 6).every((p) => p.x === 260)).toBe(true)
    expect(ps.slice(6).map((p) => p.x)).toEqual([500, 500])
    // the second column holds two notes, centred on its own
    expect(ps[6].y).toBe(75 - (2 * NOTE_H + 16) / 2)
    // start continues the numbering: a later batch lands in the slots after the first
    expect(fanPositions(srcBounds, 2, 6)).toEqual(ps.slice(6))
  })

  it('notePlacement prefers saved position', () => {
    expect(notePlacement(opt({ id: 'o1', x: 900, y: -40 }), 0, srcBounds)).toEqual({ x: 900, y: -40 })
    expect(notePlacement(opt({ id: 'o1' }), 0, srcBounds)).toEqual(fanPositions(srcBounds, 1, 0)[0])
    expect(notePlacement(opt({ id: 'o2' }), 1, srcBounds, 3)).toEqual(fanPositions(srcBounds, 3, 0)[1])
  })

  it('places every live option of a source in one fan, across explorations', () => {
    const e1 = exploration([opt({ id: 'o1' }), opt({ id: 'o2', status: 'dismissed' }), opt({ id: 'o3' })])
    const e2 = exploration([opt({ id: 'o4', exploration_id: 'e2' })], { id: 'e2', key: 'dial_color', created_at: '2026-10-29T00:00:00Z' })
    const notes = placedNotes([e1, e2], [source])
    expect(notes.map((n) => n.option.id)).toEqual(['o1', 'o3', 'o4'])
    expect(notes.map((n) => ({ x: n.x, y: n.y }))).toEqual(fanPositions(srcBounds, 3, 0))
    expect(notes[2].exploration.key).toBe('dial_color')
  })
})

describe('noteLines', () => {
  it('noteLines branch connects to parent', () => {
    const e = exploration([opt({ id: 'o1', x: 300, y: 0 }), opt({ id: 'o2', parent_option_id: 'o1', x: 600, y: 0 })])
    const lines = noteLines([e], [source])
    const note = (x: number, y: number) => ({ x, y, width: NOTE_W, height: NOTE_H })
    expect(lines).toEqual([
      { id: 'note-o1', points: lineagePoints(srcBounds, note(300, 0)) },
      { id: 'note-o2', points: lineagePoints(note(300, 0), note(600, 0)) },
    ])
  })

  it('a branch of a dismissed option joins the source', () => {
    const e = exploration([
      opt({ id: 'o1', status: 'dismissed', x: 300, y: 0 }),
      opt({ id: 'o2', parent_option_id: 'o1', x: 600, y: 0 }),
    ])
    expect(noteLines([e], [source])).toEqual([
      { id: 'note-o2', points: lineagePoints(srcBounds, { x: 600, y: 0, width: NOTE_W, height: NOTE_H }) },
    ])
  })

  it('noteLines links generated item', () => {
    const e = exploration([opt({ id: 'o1', x: 300, y: 0 })])
    const gen = makeItem({ id: 'gen', x: 600, y: 0, w: 100, h: 100, explore_option_id: 'o1', parent_item_id: 'src' })
    const other = makeItem({ id: 'other', x: 900, y: 0, explore_option_id: 'gone' })
    const lines = noteLines([e], [source, gen, other])
    expect(lines.map((l) => l.id)).toEqual(['note-o1', 'gen-gen'])
    expect(lines[1].points).toEqual(
      lineagePoints({ x: 300, y: 0, width: NOTE_W, height: NOTE_H }, { x: 600, y: 0, width: 100, height: 100 }),
    )
  })

  it('noteLines skips removed source', () => {
    const e = exploration([opt({ id: 'o1', x: 300, y: 0 })])
    const gen = makeItem({ id: 'gen', explore_option_id: 'o1' })
    expect(noteLines([e], [gen])).toEqual([])
    expect(placedNotes([e], [gen])).toEqual([])
  })
})
