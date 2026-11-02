import { describe, expect, it } from 'vitest'
import type { AnalysisView, Exploration, Item } from '../api'
import { calloutSize, WHOLE } from '../map/cards'
import { makeItem } from '../test/fixtures'
import { analysis, exp, item, opt } from '../test/explore'
import { FEEL } from './physics'
import { CALLOUT_GAP, CALLOUT_W, ellipsePoint, HUB_GAP, KEPT_EXTRA, petalAngles, petalRadius, ringAngles } from './ring'
import { buildScene, type SceneInput } from './scene'

const scene = (over: Partial<SceneInput> & { explorations: Exploration[] }) =>
  buildScene({
    items: [item],
    analyses: new Map<string, AnalysisView | null>([['a', analysis]]),
    labels: new Map(),
    collapsed: () => false,
    selectedId: null,
    ...over,
  })

const spec = (s: ReturnType<typeof buildScene>, id: string) => s.specs.find((b) => b.id === id)
const edge = (s: ReturnType<typeof buildScene>, id: string) => s.edges.find((e) => e.id === id)
// item 'a' is 200x150 at the origin; the hands part sits at (170, 75), relative (70, 0) to its centre
const handsFrac = { fx: 0.85, fy: 0.5 }
const cardAngles = ringAngles({ w: 200, h: 150 }, [{ x: 70, y: 0 }, null]) // [hands, whole]

const take = (id: string, over: Partial<Item> = {}) => makeItem({ id, board_id: 'b1', x: 600, y: 0, w: 168, h: 105, ...over })

describe('buildScene', () => {
  it("a flower's hub is rel to its source with the stored dx/dy", () => {
    const s = scene({ explorations: [exp('e1', 'hand_style', [opt('o1'), opt('o2')], 'a', { dx: 40, dy: 300 })] })
    expect(spec(s, 'a')).toMatchObject({ kind: 'item', w: 200, h: 150, home: { kind: 'abs', x: 100, y: 75 } })
    expect(spec(s, 'hub:e1')).toMatchObject({ kind: 'hub', home: { kind: 'rel', to: 'a', dx: 40, dy: 300 }, start: { x: 170, y: 75 }, delay: 0 })
    const dir = Math.atan2(300, 40)
    const angles = petalAngles(dir, 2)
    const R = petalRadius(2)
    expect(spec(s, 'petal:o2')).toMatchObject({ kind: 'petal', w: 88, h: 88, delay: FEEL.hubLeadMs + FEEL.petalStaggerMs })
    expect(spec(s, 'petal:o2')!.home).toMatchObject({ kind: 'rel', to: 'hub:e1' })
    const h = spec(s, 'petal:o2')!.home as { dx: number; dy: number }
    expect(h.dx).toBeCloseTo(Math.cos(angles[1]) * R)
    expect(h.dy).toBeCloseTo(Math.sin(angles[1]) * R)
    expect(edge(s, 'stem:e1')).toEqual({ id: 'stem:e1', kind: 'stem', from: { body: 'a', anchor: handsFrac }, to: { body: 'hub:e1' } })
    expect(edge(s, 'spoke:o1')).toEqual({ id: 'spoke:o1', kind: 'spoke', from: { body: 'hub:e1' }, to: { body: 'petal:o1' } })
    expect(s.flowers[0]).toMatchObject({ id: 'e1', hubId: 'hub:e1', sourceId: 'a', key: 'hand_style', label: 'Hand style', part: 'Hands', collapsed: false })
  })

  it('without dx/dy the hub sits at the callout slot angle', () => {
    const s = scene({ explorations: [exp('e1', 'hand_style', [opt('o1')]), exp('e2', 'mood', [opt('o2')], 'a', { dx: null, dy: null })] })
    const hands = ellipsePoint({ w: 200, h: 150 }, cardAngles[0], HUB_GAP)
    const whole = ellipsePoint({ w: 200, h: 150 }, cardAngles[1], HUB_GAP)
    expect(spec(s, 'hub:e1')!.home).toEqual({ kind: 'rel', to: 'a', dx: hands.x, dy: hands.y })
    expect(spec(s, 'hub:e2')!.home).toEqual({ kind: 'rel', to: 'a', dx: whole.x, dy: whole.y })
    // a whole-item dimension: the stem leaves where the item's edge faces the hub
    expect(edge(s, 'stem:e2')!.from).toEqual({ body: 'a' })
    expect(spec(s, 'hub:e2')!.start).toEqual({ x: 100, y: 75 })
  })

  it('a flower whose analysis is missing opens downward and still has a stem', () => {
    const s = scene({ explorations: [exp('e1', 'hand_style', [opt('o1')])], analyses: new Map([['a', null]]) })
    const home = spec(s, 'hub:e1')!.home as { dx: number; dy: number }
    expect(home.dx).toBeCloseTo(0)
    expect(home.dy).toBeCloseTo(75 + HUB_GAP.y)
    expect(edge(s, 'stem:e1')).toMatchObject({ from: { body: 'a' }, to: { body: 'hub:e1' } })
    expect(s.flowers[0]).toMatchObject({ label: 'hand_style', part: null })
  })

  it('a flower whose analysis is still loading waits (no hub) unless it has a stored offset', () => {
    const options = [opt('o1'), opt('o2', { kept_item_id: 't1' })]
    const exps = [exp('e1', 'hand_style', options), exp('e2', 'mood', [opt('o3')], 'a', { dx: 0, dy: 300 })]
    const s = scene({ items: [item, take('t1')], explorations: exps, analyses: new Map() })
    expect(s.flowers.map((f) => f.id)).toEqual(['e2'])
    expect(spec(s, 'hub:e1')).toBeUndefined()
    expect(spec(s, 'petal:o1')).toBeUndefined()
    expect(edge(s, 'stem:e1')).toBeUndefined()
    // its docked take is an ordinary item until the flower appears
    expect(spec(s, 't1')).toMatchObject({ kind: 'item', home: { kind: 'abs' } })
    expect(s.docked.size).toBe(0)
    // a stored offset does not depend on the analysis: the hub is there, its stem leaves the item's edge
    expect(spec(s, 'hub:e2')).toMatchObject({ kind: 'hub', home: { kind: 'rel', to: 'a', dx: 0, dy: 300 } })
    expect(edge(s, 'stem:e2')).toMatchObject({ from: { body: 'a' }, to: { body: 'hub:e2' } })
  })

  it('petals grow in one after another, skipping kept options', () => {
    const options = [opt('o1'), opt('o2', { kept_item_id: 't1' }), opt('o3'), opt('o4')]
    const s = scene({ items: [item, take('t1')], explorations: [exp('e1', 'hand_style', options)] })
    expect(['petal:o1', 'petal:o3', 'petal:o4'].map((id) => spec(s, id)!.delay)).toEqual([0, 1, 2].map((i) => FEEL.hubLeadMs + i * FEEL.petalStaggerMs))
  })

  it('a kept take is docked: kind kept, rel to its hub, and no petal for its option', () => {
    const options = [opt('o1'), opt('o2', { kept_item_id: 't1', status: 'kept' }), opt('o3', { status: 'dismissed' }), opt('o4')]
    const s = scene({ items: [item, take('t1')], explorations: [exp('e1', 'hand_style', options, 'a', { dx: 0, dy: 300 })] })
    expect(spec(s, 'petal:o2')).toBeUndefined()
    expect(spec(s, 'petal:o3')).toBeUndefined()
    expect(s.specs.filter((b) => b.kind === 'petal').map((b) => b.id)).toEqual(['petal:o1', 'petal:o4'])
    const t = spec(s, 't1')!
    expect(t).toMatchObject({ kind: 'kept', w: 168, h: 105, home: { kind: 'rel', to: 'hub:e1' } })
    const a = petalAngles(Math.PI / 2, 3)[1] // o1, o2, o4: the kept option keeps its slot
    const R = petalRadius(3) + KEPT_EXTRA
    const h = t.home as { dx: number; dy: number }
    expect(h.dx).toBeCloseTo(Math.cos(a) * R)
    expect(h.dy).toBeCloseTo(Math.sin(a) * R)
    expect(edge(s, 'spoke:o2')).toEqual({ id: 'spoke:o2', kind: 'spoke', from: { body: 'hub:e1' }, to: { body: 't1' }, kept: true })
    expect(s.docked).toEqual(new Map([['t1', { optionId: 'o2', hubId: 'hub:e1' }]]))
  })

  it('an undocked take is an ordinary item', () => {
    const options = [opt('o1'), opt('o2', { kept_item_id: 't1', status: 'kept', undocked: true })]
    const s = scene({ items: [item, take('t1')], explorations: [exp('e1', 'hand_style', options)] })
    expect(spec(s, 't1')).toMatchObject({ kind: 'item', home: { kind: 'abs', x: 684, y: 52.5 } })
    expect(spec(s, 'petal:o2')).toBeUndefined()
    expect(edge(s, 'spoke:o2')).toBeUndefined()
    expect(s.docked.size).toBe(0)
    // it keeps its ring slot (where it would dock), for a drop back near it to dock it again
    const dockedOpts = [options[0], { ...options[1], undocked: false }]
    const d = scene({ items: [item, take('t1')], explorations: [exp('e1', 'hand_style', dockedOpts)] })
    expect(s.slots.get('t1')).toEqual({ optionId: 'o2', hubId: 'hub:e1', index: 1, reach: petalRadius(2), home: spec(d, 't1')!.home })
    expect(d.slots.get('t1')).toEqual(s.slots.get('t1'))
  })

  it('a staged take is not on the board', () => {
    const options = [opt('o1', { kept_item_id: 't1' })]
    const s = scene({ items: [item, take('t1', { staged: true })], explorations: [exp('e1', 'hand_style', options)] })
    expect(spec(s, 't1')).toBeUndefined()
    expect(s.docked.size).toBe(0)
  })

  it('callouts only for the selected item, and its stems route through them', () => {
    const exps = [exp('e1', 'hand_style', [opt('o1')]), exp('e2', 'mood', [opt('o2')])]
    expect(scene({ explorations: exps }).specs.some((b) => b.kind === 'callout')).toBe(false)
    const s = scene({ explorations: exps, selectedId: 'a', formsOn: (card) => (card === WHOLE ? 1 : 0) })
    const callouts = s.specs.filter((b) => b.kind === 'callout')
    expect(callouts.map((b) => b.id)).toEqual(['callout:a:hands', 'callout:a:whole:item'])
    const hands = ellipsePoint({ w: 200, h: 150 }, cardAngles[0], CALLOUT_GAP)
    expect(callouts[0]).toEqual({
      id: 'callout:a:hands', kind: 'callout', ...calloutSize(item, analysis, 'hands'), home: { kind: 'rel', to: 'a', dx: hands.x, dy: hands.y }, ignore: 'a',
    })
    expect(callouts[1]).toMatchObject({ w: CALLOUT_W, h: calloutSize(item, analysis, WHOLE, 1).h })
    expect(edge(s, 'leader:e1')).toEqual({ id: 'leader:e1', kind: 'leader', from: { body: 'a', anchor: handsFrac }, to: { body: 'callout:a:hands' } })
    expect(edge(s, 'stem:e1')).toEqual({ id: 'stem:e1', kind: 'stem', from: { body: 'callout:a:hands' }, to: { body: 'hub:e1' } })
    expect(edge(s, 'leader:e2')).toMatchObject({ from: { body: 'a' }, to: { body: 'callout:a:whole:item' } })
    expect(edge(s, 'stem:e2')).toMatchObject({ from: { body: 'callout:a:whole:item' }, to: { body: 'hub:e2' } })
  })

  it('a collapsed flower is one badge and its docked takes stay', () => {
    const options = [opt('o1'), opt('o2', { kept_item_id: 't1' })]
    const s = scene({ items: [item, take('t1')], explorations: [exp('e1', 'hand_style', options, 'a', { dx: 0, dy: 300 })], collapsed: (id) => id === 'e1' })
    expect(spec(s, 'hub:e1')).toMatchObject({ kind: 'badge', w: 120, h: 28, home: { kind: 'rel', to: 'a', dx: 0, dy: 300 } })
    expect(s.specs.some((b) => b.kind === 'petal' || b.kind === 'hub')).toBe(false)
    const a = petalAngles(Math.PI / 2, 2)[1]
    const h = spec(s, 't1')!.home as { to: string; dx: number; dy: number }
    expect(spec(s, 't1')!.kind).toBe('kept')
    expect(h.to).toBe('hub:e1')
    expect(h.dx).toBeCloseTo(Math.cos(a) * 70)
    expect(h.dy).toBeCloseTo(Math.sin(a) * 70)
    expect(s.edges.map((e) => e.id)).toEqual(['stem:e1', 'spoke:o2'])
    expect(s.flowers[0].collapsed).toBe(true)
  })

  it('a take of a kept option nested on a docked take gets its own flower', () => {
    const outer = exp('e1', 'hand_style', [opt('o1', { kept_item_id: 't1' })])
    const inner = exp('e2', 'mood', [opt('o2', { exploration_id: 'e2' })], 't1')
    const s = scene({ items: [item, take('t1')], explorations: [outer, inner], analyses: new Map<string, AnalysisView | null>([['a', analysis], ['t1', null]]) })
    expect(spec(s, 't1')!.kind).toBe('kept')
    expect(spec(s, 'hub:e2')!.home).toMatchObject({ kind: 'rel', to: 't1' })
    expect(edge(s, 'stem:e2')).toMatchObject({ from: { body: 't1' }, to: { body: 'hub:e2' } })
    expect(s.flowers.map((f) => [f.id, f.sourceId])).toEqual([['e1', 'a'], ['e2', 't1']])
  })

  // from the old map model (useMap)
  it('dismissed options are no petals', () => {
    const s = scene({ explorations: [exp('e1', 'hand_style', [opt('o1'), opt('o2', { status: 'dismissed' }), opt('o3')])] })
    expect(s.flowers[0].options.map((o) => o.id)).toEqual(['o1', 'o3'])
    expect(spec(s, 'petal:o2')).toBeUndefined()
  })

  it('a flower whose item is not on the board has nothing, and holds back no other', () => {
    const s = scene({ explorations: [exp('e0', 'hand_style', [opt('o0')], 'gone'), exp('e1', 'hand_style', [opt('o1')])] })
    expect(s.flowers.map((f) => f.id)).toEqual(['e1'])
    expect(spec(s, 'hub:e0')).toBeUndefined()
  })

  it('a dimension gone from the analysis is labelled from the lens, on no part, its stem from the item edge', () => {
    const s = scene({ explorations: [exp('e1', 'old_key', [opt('o1')])], labels: new Map([['old_key', 'Old key']]) })
    expect(s.flowers[0]).toMatchObject({ label: 'Old key', part: null })
    expect(edge(s, 'stem:e1')!.from).toEqual({ body: 'a' })
    // no lens label either: the key itself
    expect(scene({ explorations: [exp('e1', 'old_key', [opt('o1')])] }).flowers[0].label).toBe('old_key')
  })

  it("the selection toolbar is an obstacle centred just above the selected item, and nowhere else", () => {
    const toolbar = { w: 240, h: 50 }
    expect(scene({ explorations: [], toolbar }).specs.some((b) => b.kind === 'obstacle')).toBe(false)
    const other = makeItem({ id: 'b', board_id: 'b1', x: 600, y: 0 })
    const s = scene({ items: [item, other], explorations: [], selectedId: 'a', toolbar })
    const obstacles = s.specs.filter((b) => b.kind === 'obstacle')
    expect(obstacles).toEqual([
      { id: 'toolbar:a', kind: 'obstacle', w: 240, h: 50, home: { kind: 'rel', to: 'a', dx: 0, dy: -(75 + 25) }, ignore: 'a' },
    ])
    expect(s.edges.some((e) => e.from.body === 'toolbar:a' || e.to.body === 'toolbar:a')).toBe(false)
  })

  it("a callout's measured height wins over the estimate", () => {
    const s = scene({ explorations: [], selectedId: 'a', calloutHeights: new Map([['hands', 140]]) })
    expect(spec(s, 'callout:a:hands')!.h).toBe(140)
    expect(spec(s, 'callout:a:whole:item')!.h).toBe(calloutSize(item, analysis, WHOLE).h)
  })
})
