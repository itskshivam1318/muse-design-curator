import { describe, expect, it } from 'vitest'
import type { AnalysisView, Item } from '../api'
import { makeItem } from '../test/fixtures'
import { analysis, exp, item, opt } from '../test/explore'
import { staleDocked } from './dockIn'
import { buildScene } from './scene'

// item 'a' has a flower e1; its kept option o2's take t1 is docked in the ring unless undocked
const t1 = makeItem({ id: 't1', board_id: 'b1', x: 600, y: 0, w: 400, h: 300, origin: 'generated', explore_option_id: 'o2' })

function stale(over: { t1?: Partial<Item>; undocked?: boolean } = {}) {
  const items = [item, { ...t1, ...over.t1 }]
  const scene = buildScene({
    items,
    explorations: [exp('e1', 'hand_style', [opt('o1'), opt('o2', { kept_item_id: 't1', status: 'kept', undocked: !!over.undocked })], 'a', { dx: 300, dy: 0 })],
    analyses: new Map<string, AnalysisView | null>([['a', analysis]]),
    labels: new Map(),
    collapsed: () => false,
    selectedId: null,
  })
  return staleDocked(scene, items, () => ({ x: 1000, y: 500 }))
}

describe('staleDocked', () => {
  it('a full-size kept take is stale', () => {
    // moved to its slot (centre 1000, 500) at the docked size: 168 wide, same aspect
    expect(stale()).toEqual([{ id: 't1', x: 916, y: 437, w: 168, h: 126 }])
  })

  it('a docked-size take is not', () => {
    expect(stale({ t1: { w: 168, h: 126 } })).toEqual([])
    expect(stale({ t1: { w: 168.6, h: 126 } })).toEqual([]) // within a pixel
  })

  it('undocked takes are never stale', () => {
    expect(stale({ undocked: true })).toEqual([])
  })
})
