import { describe, expect, it } from 'vitest'
import type { AnalysisView, Exploration } from '../api'
import { analysis, exp, item, opt } from '../living/fixtures'
import { makeItem } from '../test/fixtures'
import { calloutBounds, WHOLE } from './cards'
import { mapModel } from './useMap'

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

  describe('draws flowers in id order up to the first item still loading', () => {
    const other = makeItem({ id: 'b', board_id: 'b1', x: 0, y: 600, w: 200, h: 150 })
    const model = (exps: Exploration[], analyses: Map<string, AnalysisView | null>) =>
      mapModel(exps, [item, other], analyses, () => false, new Map()).flowers.map((f) => f.id)

    it('a later flower on a loading item waits; earlier ones draw; one off the board blocks nothing', () => {
      const exps = [exp('e0', 'hand_style', [opt('o0')], 'gone'), exp('e1', 'hand_style', [opt('o1')]), exp('e2', 'hand_style', [opt('o2')], 'b')]
      expect(model(exps, new Map([['a', analysis]]))).toEqual(['e1'])
    })

    it('an earlier flower on a loading item holds back every later one', () => {
      const exps = [exp('e2', 'hand_style', [opt('o2')]), exp('e1', 'hand_style', [opt('o1')], 'b')]
      expect(model(exps, new Map([['a', analysis]]))).toEqual([])
      expect(model(exps, new Map([['a', analysis], ['b', analysis]]))).toEqual(['e1', 'e2'])
    })

    it('a failed analysis settles: its flower starts at the item edge, with no callouts', () => {
      const exps = [exp('e1', 'hand_style', [opt('o1')], 'b'), exp('e2', 'hand_style', [opt('o2')])]
      const { flowers, callouts } = mapModel(exps, [item, other], new Map([['a', analysis], ['b', null]]), () => false, new Map())
      expect(flowers.map((f) => f.id)).toEqual(['e1', 'e2'])
      expect(flowers[0]).toMatchObject({ dir: 0, from: { x: 200, y: 675 }, label: 'hand_style', part: null })
      expect([...callouts.keys()]).toEqual(['a'])
    })
  })

  it('a dimension gone from the analysis starts at the Whole item card, labelled from the lens', () => {
    const { flowers } = mapModel([exp('e1', 'old_key', [opt('o1')])], [item], new Map([['a', analysis]]), () => false, new Map([['old_key', 'Old key']]))
    const whole = calloutBounds(item, analysis, []).get(WHOLE)!
    expect(flowers[0]).toMatchObject({ label: 'Old key', part: null })
    expect(flowers[0].from.y).toBeCloseTo(whole.y + whole.height)
  })
})
