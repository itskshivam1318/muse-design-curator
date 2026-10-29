import { describe, expect, it } from 'vitest'
import type { Exploration, ExploreOption } from '../api'
import { makeItem } from '../test/fixtures'
import {
  AXIS_GAP_X,
  axisRows,
  CARD_GAP,
  CARD_W,
  cardOptionId,
  drawnAxes,
  keptOnCard,
  keptSlot,
  ROW_H,
  rowBounds,
} from './axis'

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: over.id, description: '',
    distance: 'near', value: over.id, keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [],
    x: null, y: null, created_at: '2026-10-28T00:00:00Z', ...over,
  }
}

function exp(id: string, created_at: string, options: ExploreOption[], item_id = 'src'): Exploration {
  return { id, board_id: 'b1', item_id, key: `key_${id}`, created_at, options: options.map((o) => ({ ...o, exploration_id: id })) }
}

const SOURCE = { x: 100, y: 50, width: 200, height: 150 }

describe('axisRows', () => {
  it('two explorations → two rows 132 px apart, oldest first, line from the source right edge', () => {
    const later = exp('e2', '2026-10-28T00:00:02Z', [opt({ id: 'b' })])
    const first = exp('e1', '2026-10-28T00:00:01Z', [opt({ id: 'a' })])
    const rows = axisRows(SOURCE, [later, first], new Map([['key_e1', 'Dial colour']]))
    expect(rows.map((r) => r.exploration_id)).toEqual(['e1', 'e2'])
    expect(rows[1].y - rows[0].y).toBe(ROW_H)
    expect(rows[0].y).toBeGreaterThanOrEqual(SOURCE.y)
    expect(rows[0].x0).toBe(SOURCE.x + SOURCE.width + AXIS_GAP_X)
    expect(rows[0].label).toBe('Dial colour')
    expect(rows[1].label).toBe('key_e2') // no label known: the key
  })

  it('leaves dismissed options and branches off the axis, and an exploration with no cards gets no row', () => {
    const e1 = exp('e1', '2026-10-28T00:00:01Z', [
      opt({ id: 'a' }),
      opt({ id: 'b', status: 'dismissed' }),
      opt({ id: 'a1', parent_option_id: 'a', batch: 2 }),
      opt({ id: 'c' }),
    ])
    const gone = exp('e2', '2026-10-28T00:00:02Z', [opt({ id: 'x', status: 'dismissed' })])
    const e3 = exp('e3', '2026-10-28T00:00:03Z', [opt({ id: 'z' })])
    const rows = axisRows(SOURCE, [e1, gone, e3])
    expect(rows.map((r) => r.exploration_id)).toEqual(['e1', 'e3'])
    expect(rows[0].cards.map((c) => c.option_id)).toEqual(['a', 'c'])
    expect(rows[1].y - rows[0].y).toBe(ROW_H) // stacking skips the row that is not drawn
  })

  it('spaces cards evenly from x0 and ends the line past the last card', () => {
    const [row] = axisRows(SOURCE, [exp('e1', '', [opt({ id: 'a' }), opt({ id: 'b' }), opt({ id: 'c' })])])
    expect(row.cards.map((c) => c.x)).toEqual([0, 1, 2].map((i) => row.x0 + i * (CARD_W + CARD_GAP)))
    expect(row.cards.every((c) => c.w === CARD_W && c.y > row.y)).toBe(true)
    expect(row.x1).toBeGreaterThan(row.cards[2].x + CARD_W)
    const b = rowBounds(row)
    expect(b.x + b.width).toBeGreaterThan(row.x1) // the end handle is inside
    expect(b.y + b.height).toBeGreaterThanOrEqual(row.cards[0].y + row.cards[0].h)
  })

  it('keptSlot is the card position', () => {
    const [row] = axisRows(SOURCE, [exp('e1', '', [opt({ id: 'a' }), opt({ id: 'b' })])])
    expect(keptSlot(row, 'b')).toEqual({ x: row.cards[1].x, y: row.cards[1].y })
    expect(keptSlot(row, 'nope')).toBeUndefined()
  })
})

describe('cards and kept items', () => {
  it('a branch belongs to the card of its top-level option', () => {
    const e = exp('e1', '', [opt({ id: 'a' }), opt({ id: 'a1', parent_option_id: 'a' }), opt({ id: 'a1x', parent_option_id: 'a1' })])
    expect(cardOptionId(e, 'a1x')).toBe('a')
    expect(cardOptionId(e, 'a')).toBe('a')
  })

  it('a card shows its own kept take, else a kept branch take, and only when the item is on the board', () => {
    const items = new Map([['k1', makeItem({ id: 'k1' })], ['k2', makeItem({ id: 'k2' })]])
    const e = exp('e1', '', [
      opt({ id: 'a', kept_item_id: 'k1', takes: ['k1'] }),
      opt({ id: 'b' }),
      opt({ id: 'b1', parent_option_id: 'b', kept_item_id: 'k2', takes: ['k2'] }),
      opt({ id: 'c', kept_item_id: 'gone', takes: [] }),
    ])
    expect(keptOnCard(e, 'a', items)?.item.id).toBe('k1')
    expect(keptOnCard(e, 'b', items)).toMatchObject({ item: { id: 'k2' }, option: { id: 'b1' } })
    expect(keptOnCard(e, 'c', items)).toBeNull()
  })
})

describe('drawnAxes', () => {
  it('draws axes of visible sources only, and hides the kept items the cards show', () => {
    const src = makeItem({ id: 'src', x: 0, y: 0, w: 200, h: 150 })
    const kept = makeItem({ id: 'k1', x: 240, y: 28, w: 240, h: 240 })
    const staged = makeItem({ id: 'st', staged: true })
    const list = [
      exp('e1', '2026-10-28T00:00:01Z', [opt({ id: 'a', kept_item_id: 'k1', takes: ['k1'] })]),
      exp('e2', '2026-10-28T00:00:02Z', [opt({ id: 'z' })], 'k1'), // the kept take explored: its source is now a card
      exp('e3', '2026-10-28T00:00:03Z', [opt({ id: 'y' })], 'st'), // a staged source is not on the canvas
      exp('e4', '2026-10-28T00:00:04Z', [opt({ id: 'w' })], 'removed'),
    ]
    const out = drawnAxes([src, kept, staged], list)
    expect([...out.hidden]).toEqual(['k1'])
    const card = out.axes[0].rows[0].cards[0]
    expect(out.cards.get('k1')).toEqual({ x: card.x, y: card.y, width: card.w, height: card.h })
    expect(out.axes.map((a) => [a.source.id, a.rows.map((r) => r.exploration_id)])).toEqual([['src', ['e1']]])
  })

  it('an un-kept take that was explored draws its own axis again', () => {
    const src = makeItem({ id: 'src' })
    const take = makeItem({ id: 'k1', x: 600 })
    const list = [
      exp('e1', '2026-10-28T00:00:01Z', [opt({ id: 'a', takes: ['k1'], status: 'visualized' })]),
      exp('e2', '2026-10-28T00:00:02Z', [opt({ id: 'z' })], 'k1'),
    ]
    const out = drawnAxes([src, take], list)
    expect(out.hidden.size).toBe(0)
    expect(out.axes.map((a) => a.source.id)).toEqual(['src', 'k1'])
  })
})
