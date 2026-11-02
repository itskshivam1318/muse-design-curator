import { describe, expect, it } from 'vitest'
import type { AnalysisView, Exploration, ExploreOption } from '../api'
import { makeItem } from '../test/fixtures'
import { calloutBounds, WHOLE } from './cards'
import { mapModel } from './useMap'

const opt = (id: string, over: Partial<ExploreOption> = {}): ExploreOption => ({
  id, exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: id, description: '', distance: 'near',
  value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null, ...over,
})

const analysis: AnalysisView = {
  content_type: 'image',
  parse_status: 'completed',
  // a part on the right third: its callout goes to the right of the item
  parts: [{ key: 'hands', label: 'Hands', region_kind: 'box', region: [0.8, 0.4, 0.9, 0.6], mask_url: null, source: 'ai' }],
  dimensions: [
    { key: 'hand_style', label: 'Hand style', type: 'physical', part: 'hands', prompt: null, kind: 'enum', value: 'x', confidence: 1, source: 'ai', status: 'extracted' },
    { key: 'mood', label: 'Mood', type: 'abstract', part: null, prompt: null, kind: 'enum', value: 'x', confidence: 1, source: 'ai', status: 'extracted' },
  ],
}

const item = makeItem({ id: 'a', board_id: 'b1', x: 0, y: 0, w: 200, h: 150 })
const exp = (id: string, key: string, options: ExploreOption[], itemId = 'a'): Exploration => ({ id, board_id: 'b1', item_id: itemId, key, options })

describe('mapModel', () => {
  it('starts each flower at the far edge of its dimension card, opening away from the item', () => {
    const { flowers, callouts } = mapModel(
      [exp('e1', 'hand_style', [opt('o1'), opt('o2', { status: 'dismissed' }), opt('o3', { status: 'kept' })]), exp('e2', 'mood', [opt('o4')])],
      [item],
      new Map([['a', analysis]]),
      (id) => id === 'e2',
      new Map(),
    )
    const slots = calloutBounds(item, analysis, [])
    expect(callouts).toEqual(new Map([['a', [...slots.values()]]]))
    const [hands, mood] = flowers
    const slot = slots.get('hands')!
    expect(hands).toMatchObject({ id: 'e1', itemId: 'a', key: 'hand_style', label: 'Hand style', part: 'Hands', collapsed: false })
    expect(hands.options.map((o) => o.id)).toEqual(['o1', 'o3']) // dismissed ones are no petals
    // to the right: dir ~ 0 and `from` on the slot's right edge
    expect(Math.abs(hands.dir)).toBeLessThan(Math.PI / 4)
    expect(hands.from.x).toBeCloseTo(slot.x + slot.width)
    // an abstract dimension starts at the Whole item card, below the item
    const whole = slots.get(WHOLE)!
    expect(mood).toMatchObject({ label: 'Mood', part: null, collapsed: true })
    expect(mood.dir).toBeGreaterThan(0)
    expect(mood.from.y).toBeCloseTo(whole.y + whole.height)
  })

  it('draws no flower for an item off the board or whose analysis has not loaded', () => {
    const other = makeItem({ id: 'b', board_id: 'b1', x: 0, y: 600, w: 200, h: 150 })
    const { flowers, callouts } = mapModel(
      [exp('e1', 'hand_style', [opt('o1')]), exp('e2', 'hand_style', [opt('o2')], 'gone'), exp('e3', 'hand_style', [opt('o3')], 'b')],
      [item, other],
      new Map([['a', analysis]]),
      () => false,
      new Map(),
    )
    expect(flowers.map((f) => f.id)).toEqual(['e1'])
    expect([...callouts.keys()]).toEqual(['a'])
  })

  it('a dimension gone from the analysis starts at the Whole item card, labelled from the lens', () => {
    const { flowers } = mapModel([exp('e1', 'old_key', [opt('o1')])], [item], new Map([['a', analysis]]), () => false, new Map([['old_key', 'Old key']]))
    const whole = calloutBounds(item, analysis, []).get(WHOLE)!
    expect(flowers[0]).toMatchObject({ label: 'Old key', part: null })
    expect(flowers[0].from.y).toBeCloseTo(whole.y + whole.height)
  })
})
