import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { type Exploration, type Item, keys, type NodesResponse, type PluginNode, type PluginRun } from './api'
import { applyEvent, connectBoardEvents, boardActivity, type DescribeContext, describeEvent, noteVisualizeStore, seedVisualizing } from './events'
import { countedItems, visibleItems } from './queries'
import { makeItem } from './test/fixtures'

function qcWith(items: Item[]) {
  const qc = new QueryClient()
  qc.setQueryData(keys.items('b'), items)
  return qc
}

const exploration = (over: Partial<Exploration> = {}): Exploration => ({
  id: 'x1',
  board_id: 'b',
  item_id: 'i1',
  key: 'colour',
  options: [],
  ...over,
})

describe('applyEvent', () => {
  it('explore.updated upserts the exploration by id', () => {
    const qc = new QueryClient()
    applyEvent(qc, 'b', 'explore.updated', exploration())
    applyEvent(qc, 'b', 'explore.updated', exploration({ id: 'x2' }))
    applyEvent(qc, 'b', 'explore.updated', exploration({ key: 'shape' }))
    const list = qc.getQueryData<Exploration[]>(keys.explorations('b'))!
    expect(list.map((e) => [e.id, e.key])).toEqual([
      ['x1', 'shape'],
      ['x2', 'colour'],
    ])
  })

  it('explore.updated for another board is ignored', () => {
    const qc = new QueryClient()
    applyEvent(qc, 'b', 'explore.updated', exploration({ board_id: 'other' }))
    expect(qc.getQueryData(keys.explorations('b'))).toBeUndefined()
  })

  it('board.updated also refreshes item attributes (the lens vocabulary may have grown)', () => {
    const qc = new QueryClient()
    qc.setQueryData(keys.attributes('i1'), {})
    applyEvent(qc, 'b', 'board.updated', { board: { id: 'b' } })
    expect(qc.getQueryState(keys.attributes('i1'))?.isInvalidated).toBe(true)
  })

  it('board.updated puts the new board (domain) in the cache and refreshes the lens', () => {
    const qc = qcWith([])
    const board = { id: 'b', title: 'T', context: '', domain: null, lens_id: null, created_at: 'x', updated_at: 'x' }
    qc.setQueryData(keys.board('b'), board)
    qc.setQueryData(keys.lens('b'), null)
    applyEvent(qc, 'b', 'board.updated', { board: { ...board, domain: 'watch', lens_id: 'lens_1' } })
    expect(qc.getQueryData<typeof board>(keys.board('b'))).toMatchObject({ domain: 'watch', lens_id: 'lens_1' })
    expect(qc.getQueryState(keys.lens('b'))?.isInvalidated).toBe(true)
  })

  it('item.added upserts once, item.parsed and item.failed patch status, item.removed drops', () => {
    const qc = qcWith([])
    const it1 = makeItem({ id: 'i1', board_id: 'b', parse_status: 'pending' })
    applyEvent(qc, 'b', 'item.added', it1)
    applyEvent(qc, 'b', 'item.added', it1)
    expect(qc.getQueryData<Item[]>(keys.items('b'))).toHaveLength(1)
    applyEvent(qc, 'b', 'item.parsed', { item_id: 'i1', parse_status: 'completed' })
    expect(qc.getQueryData<Item[]>(keys.items('b'))![0].parse_status).toBe('completed')
    applyEvent(qc, 'b', 'item.failed', { item_id: 'i1', error_code: 'MODEL_ERROR' })
    const failed = qc.getQueryData<Item[]>(keys.items('b'))![0]
    expect([failed.parse_status, failed.parse_error_code]).toEqual(['failed', 'MODEL_ERROR'])
    applyEvent(qc, 'b', 'item.updated', { ...it1, x: 99 })
    expect(qc.getQueryData<Item[]>(keys.items('b'))![0].x).toBe(99)
    applyEvent(qc, 'b', 'item.removed', { id: 'i1' })
    expect(qc.getQueryData<Item[]>(keys.items('b'))).toHaveLength(0)
  })

  it('lens.proposed invalidates the board lens', async () => {
    const qc = qcWith([])
    qc.setQueryData(keys.lens('b'), null)
    applyEvent(qc, 'b', 'lens.proposed', { lens_id: 'lens_1', version: 1 })
    expect(qc.getQueryState(keys.lens('b'))?.isInvalidated).toBe(true)
  })
})

const node = (over: Partial<PluginNode> = {}): PluginNode => ({
  id: 'n1', board_id: 'b', plugin_id: 'palette', x: 0, y: 0, w: 300, h: 360,
  input_item_ids: [], params: {}, last_run_id: null, ...over,
})
const run = (over: Partial<PluginRun> = {}): PluginRun => ({
  id: 'r1', node_id: 'n1', plugin_id: 'palette', status: 'queued', progress: null, output: null,
  error_code: null, error_message: null, created_at: 'x', finished_at: null, ...over,
})

describe('plugin runs', () => {
  const nodesQc = () => {
    const qc = new QueryClient()
    qc.setQueryData<NodesResponse>(keys.nodes('b'), { nodes: [node()], runs: {} })
    qc.setQueryData(keys.plugins(), [{ id: 'palette', name: 'Palette & material' }])
    return qc
  }
  const runOf = (qc: QueryClient) => qc.getQueryData<NodesResponse>(keys.nodes('b'))!.runs.n1

  it('test plugin_run.done updates node run', () => {
    const qc = nodesQc()
    applyEvent(qc, 'b', 'plugin_run.queued', { node_id: 'n1', run_id: 'r1' })
    expect(runOf(qc)).toMatchObject({ id: 'r1', status: 'queued' })
    applyEvent(qc, 'b', 'plugin_run.progress', { node_id: 'n1', run_id: 'r1', progress: { message: 'Looking' } })
    expect(runOf(qc)).toMatchObject({ status: 'running', progress: { message: 'Looking' } })
    applyEvent(qc, 'b', 'plugin_run.done', { node_id: 'n1', run_id: 'r1', output: { created_item_ids: ['a'] } })
    expect(runOf(qc)).toMatchObject({ status: 'done', progress: null, output: { created_item_ids: ['a'] } })
    expect(qc.getQueryData<NodesResponse>(keys.nodes('b'))!.nodes[0].last_run_id).toBe('r1')
  })

  it('plugin_run.failed records the error', () => {
    const qc = nodesQc()
    applyEvent(qc, 'b', 'plugin_run.failed', { node_id: 'n1', run_id: 'r2', error_code: 'X', error_message: 'boom' })
    expect(runOf(qc)).toMatchObject({ id: 'r2', status: 'failed', error_code: 'X', error_message: 'boom' })
  })

  it('a stale event for an older run does not overwrite a newer one', () => {
    const qc = nodesQc()
    qc.setQueryData<NodesResponse>(keys.nodes('b'), { nodes: [node({ last_run_id: 'r2' })], runs: { n1: run({ id: 'r2', status: 'running' }) } })
    applyEvent(qc, 'b', 'plugin_run.done', { node_id: 'n1', run_id: 'r1', output: {} })
    expect(runOf(qc)).toMatchObject({ id: 'r2', status: 'running' })
  })

  it('a mismatched run event refetches the nodes instead of being dropped', () => {
    const qc = nodesQc()
    qc.setQueryData<NodesResponse>(keys.nodes('b'), { nodes: [node({ last_run_id: 'r2' })], runs: { n1: run({ id: 'r2', status: 'running' }) } })
    applyEvent(qc, 'b', 'plugin_run.failed', { node_id: 'n1', run_id: 'r1', error_message: 'x' })
    expect(qc.getQueryState(keys.nodes('b'))?.isInvalidated).toBe(true)
  })

  it('without a nodes cache it refetches nothing and does not throw', () => {
    const qc = new QueryClient()
    expect(() => applyEvent(qc, 'b', 'plugin_run.done', { node_id: 'n1', run_id: 'r1' })).not.toThrow()
    expect(qc.getQueryData(keys.nodes('b'))).toBeUndefined()
  })
})

describe('note visualizing', () => {
  it('test note.visualized clears visualizing', () => {
    const qc = new QueryClient()
    applyEvent(qc, 'b', 'note.visualizing', { note_id: 'n9' })
    expect(noteVisualizeStore.get().ids.has('n9')).toBe(true)
    applyEvent(qc, 'b', 'note.visualized', { note_id: 'n9', item_id: 'i2' })
    expect(noteVisualizeStore.get().ids.has('n9')).toBe(false)
    applyEvent(qc, 'b', 'note.visualizing', { note_id: 'n9' })
    applyEvent(qc, 'b', 'note.visualize_failed', { note_id: 'n9', error: 'nope' })
    expect(noteVisualizeStore.get().ids.has('n9')).toBe(false)
  })
})

describe('seedVisualizing', () => {
  it('a note with a fresh server claim is visualizing after a reload; a stale claim is not', () => {
    const now = Date.parse('2026-10-29T10:10:00.000+00:00')
    const fresh = makeItem({ id: 'sv1', kind: 'note', note_text: 'a', generation: { visualizing_since: '2026-10-29T10:08:00.000+00:00' } })
    const stale = makeItem({ id: 'sv2', kind: 'note', note_text: 'b', generation: { visualizing_since: '2026-10-29T10:04:00.000+00:00' } })
    const image = makeItem({ id: 'sv3', generation: { visualizing_since: '2026-10-29T10:09:00.000+00:00' } })
    const items = [fresh, stale, image, makeItem({ id: 'sv4', kind: 'note', note_text: 'c' })]
    expect(seedVisualizing(items, now)).toBe(items)
    const ids = noteVisualizeStore.get().ids
    expect([ids.has('sv1'), ids.has('sv2'), ids.has('sv3'), ids.has('sv4')]).toEqual([true, false, false, false])
  })

  it('a seeded visualizing note is cleared when a refetch returns it without a claim', () => {
    const now = Date.parse('2026-10-29T10:10:00.000+00:00')
    const claimed = makeItem({ id: 'sv5', kind: 'note', note_text: 'a', generation: { visualizing_since: '2026-10-29T10:09:00.000+00:00' } })
    seedVisualizing([claimed], now)
    expect(noteVisualizeStore.get().ids.has('sv5')).toBe(true)
    seedVisualizing([{ ...claimed, generation: null }], now)
    expect(noteVisualizeStore.get().ids.has('sv5')).toBe(false)
  })
})

describe('describeEvent', () => {
  it('test describeEvent sentences', () => {
    const ctx = { pluginName: 'Palette & material' }
    const kinds: Record<string, 'image' | 'note'> = { i1: 'image', i2: 'image', n1: 'note' }
    const known = { ...ctx, itemKind: (id: string) => kinds[id] }
    const done = (ids: string[], c: DescribeContext = known) => describeEvent('plugin_run.done', { output: { created_item_ids: ids } }, c)
    expect(done(['n1'])).toBe('Palette & material finished: 1 note added')
    expect(done(['i1', 'i2'], { ...known, pluginName: 'Image' })).toBe('Image finished: 2 images added')
    expect(done(['i1', 'i2', 'n1'])).toBe('Palette & material finished: 2 images and 1 note added')
    expect(done(['i1', 'zz'])).toBe('Palette & material finished: 2 items added')
    expect(done(['a'], ctx)).toBe('Palette & material finished: 1 item added')
    expect(describeEvent('plugin_run.done', { output: {} }, ctx)).toBe('Palette & material finished')
    expect(describeEvent('plugin_run.failed', { error_message: 'no key' }, ctx)).toBe('Palette & material failed: no key')
    expect(describeEvent('plugin_run.queued', {}, ctx)).toBe('Palette & material is running')
    expect(describeEvent('note.visualized', {}, { noteLabel: 'Honey' })).toBe('Honey visualized')
    expect(describeEvent('note.visualized', {})).toBe('Note visualized')
    expect(describeEvent('note.visualizing', {})).toBe('Visualizing note')
    expect(describeEvent('note.visualize_failed', { error: 'IMAGE_MODEL_FAILED' })).toBe('Note could not be visualized: the image model failed')
    expect(describeEvent('note.visualize_failed', { error: 'INTERRUPTED' })).toBe('Note could not be visualized: it was interrupted')
    expect(describeEvent('note.visualize_failed', { error: 'WEIRD_CODE' })).toBe('Note could not be visualized: something went wrong')
    expect(describeEvent('item.added', {})).toBeNull()
  })

  it('applyEvent feeds boardActivity (newest last, capped at 50)', () => {
    const qc = new QueryClient()
    qc.setQueryData<NodesResponse>(keys.nodes('b'), { nodes: [node()], runs: {} })
    qc.setQueryData(keys.plugins(), [{ id: 'palette', name: 'Palette' }])
    qc.setQueryData(keys.items('b'), [makeItem({ id: 'a', board_id: 'b', kind: 'note', note_text: 'oak' })])
    boardActivity.clear()
    applyEvent(qc, 'b', 'plugin_run.done', { node_id: 'n1', run_id: 'r1', output: { created_item_ids: ['a'] } })
    expect(boardActivity.get().entries.at(-1)?.text).toBe('Palette finished: 1 note added')
    for (let i = 0; i < 60; i++) applyEvent(qc, 'b', 'note.visualized', { note_id: `n${i}` })
    expect(boardActivity.get().entries).toHaveLength(50)
  })
})

describe('countedItems', () => {
  it('drops staged takes and notes (the board and onboarding counts)', () => {
    const items = [makeItem({ id: 'a' }), makeItem({ id: 'b', staged: true }), makeItem({ id: 'n', kind: 'note', note_text: 'x' })]
    expect(countedItems(items).map((i) => i.id)).toEqual(['a'])
  })
})

describe('visibleItems', () => {
  it('test visibleItems drops staged', () => {
    const items = [makeItem({ id: 'a' }), makeItem({ id: 'b', staged: true })]
    expect(visibleItems(items).map((i) => i.id)).toEqual(['a'])
  })
})

describe('connectBoardEvents', () => {
  it('refetches the items on the first open too (a job may have ended before the stream opened)', () => {
    const src = { addEventListener: () => undefined, close: () => undefined } as unknown as EventSource
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    const stop = connectBoardEvents('b3', qc, { makeSource: () => src })
    src.onopen?.(new Event('open'))
    expect(spy).toHaveBeenCalledWith({ queryKey: keys.items('b3') })
    stop()
  })

  it('routes the round 2 event types into the cache and clears activity for a new board', () => {
    const listeners: Record<string, (e: MessageEvent<string>) => void> = {}
    const src = {
      addEventListener: (t: string, l: (e: MessageEvent<string>) => void) => (listeners[t] = l),
      close: () => undefined,
    } as unknown as EventSource
    const qc = new QueryClient()
    boardActivity.push('from the previous board')
    const stop = connectBoardEvents('b2', qc, { makeSource: () => src })
    expect(boardActivity.get().entries).toEqual([])
    listeners['note.visualizing']({ data: JSON.stringify({ note_id: 'nx' }) } as MessageEvent<string>)
    expect(noteVisualizeStore.get().ids.has('nx')).toBe(true)
    listeners['note.visualized']({ data: JSON.stringify({ note_id: 'nx' }) } as MessageEvent<string>)
    expect(noteVisualizeStore.get().ids.has('nx')).toBe(false)
    for (const t of ['plugin_run.queued', 'plugin_run.progress', 'plugin_run.done', 'plugin_run.failed', 'note.visualize_failed'])
      expect(listeners[t]).toBeTypeOf('function')
    stop()
  })
})
