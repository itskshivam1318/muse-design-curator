import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys, type NodesResponse } from '../api'
import { makeItem } from '../test/fixtures'
import { makeNode, makePlugin } from '../test/plugins'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  createNode: vi.fn(),
  deleteNode: vi.fn(),
  patchNode: vi.fn(),
}))
const api = await import('../api')
const { acceptsItem, addToNode, canRun, createNodeFromSelection, nodeAt, paramFields, removeNode, shownFields, summaryLine } =
  await import('./nodeLogic')
const { selection } = await import('../canvas/selection')
const { undoHistory } = await import('../canvas/history')

afterEach(() => {
  selection.reset()
  undoHistory.clear()
})

const image = makePlugin()
const note = makeItem({ id: 'n1', kind: 'note', note_text: 'Strap' })
const photo = makeItem({ id: 'i1' })

describe('paramFields', () => {
  it('reads types, enum options, bounds and defaults', () => {
    const f = paramFields(image.params)
    expect(f.map((x) => [x.key, x.type])).toEqual([
      ['mode', 'enum'],
      ['part', 'string'],
      ['prompt', 'string'],
      ['count', 'integer'],
    ])
    expect(f[0].options).toEqual(['part', 'whole'])
    expect(f[0].default).toBe('part')
    expect(f[3]).toMatchObject({ min: 1, max: 4, default: 1, label: 'Count' })
  })

  it('honours x-show-if', () => {
    const f = paramFields(image.params)
    expect(f.find((x) => x.key === 'part')?.showIf).toEqual({ mode: 'part' })
    expect(shownFields(f, { mode: 'whole' }).map((x) => x.key)).toEqual(['mode', 'prompt', 'count'])
    expect(shownFields(f, {}).map((x) => x.key)).toContain('part') // the default mode is part
  })

  it('falls back to json for other types and tolerates a missing schema', () => {
    expect(paramFields({ properties: { tags: { type: 'array' }, on: { type: 'boolean' } } }).map((x) => x.type)).toEqual([
      'json',
      'boolean',
    ])
    expect(paramFields({})).toEqual([])
    expect(paramFields(undefined as unknown as Record<string, unknown>)).toEqual([])
  })
})

describe('summaryLine', () => {
  it('describes the image part and whole modes', () => {
    expect(summaryLine(image, { mode: 'part', part: 'dial' })).toBe('Change only the dial')
    expect(summaryLine(image, { part: 'strap' })).toBe('Change only the strap')
    expect(summaryLine(image, { mode: 'whole' })).toBe('Whole image')
    expect(summaryLine(image, { mode: 'part', part: '' })).toBe('Change only a part')
  })

  it('shows the first param of other plugins', () => {
    const palette = makePlugin({
      id: 'palette',
      params: { type: 'object', properties: { count: { type: 'integer', default: 5 } } },
    })
    expect(summaryLine(palette, {})).toBe('Count 5')
    expect(summaryLine(palette, { count: 7 })).toBe('Count 7')
    expect(summaryLine(makePlugin({ id: 'video', params: { type: 'object', properties: {} } }), {})).toBe('No settings')
  })
})

describe('acceptsItem', () => {
  it('takes the kinds the plugin reads, never staged items', () => {
    expect(acceptsItem(image, note)).toBe(true)
    expect(acceptsItem(makePlugin({ inputs: { kinds: ['image'], min: 1, max: 4 } }), note)).toBe(false)
    expect(acceptsItem(image, makeItem({ staged: true }))).toBe(false)
  })
})

describe('canRun', () => {
  const items = new Map([
    [note.id, note],
    [photo.id, photo],
  ])
  it('is ok with enough live inputs', () => {
    expect(canRun(image, makeNode({ input_item_ids: ['n1'] }), items)).toEqual({ ok: true })
  })
  it('is not for a plugin that is not connected', () => {
    const r = canRun(makePlugin({ status: 'not_connected', runs_on: '[video model]' }), makeNode({ input_item_ids: ['n1'] }), items)
    expect(r.ok).toBe(false)
    expect(r.reason).toBe('[video model] not connected')
  })
  it('is not below the minimum or above the maximum', () => {
    expect(canRun(image, makeNode({ input_item_ids: [] }), items)).toEqual({ ok: false, reason: 'Add an input' })
    const two = makePlugin({ inputs: { kinds: ['image', 'note'], min: 2, max: 2 } })
    expect(canRun(two, makeNode({ input_item_ids: ['n1'] }), items).reason).toBe('Add 1 more input')
    const one = makePlugin({ inputs: { kinds: ['image', 'note'], min: 1, max: 1 } })
    expect(canRun(one, makeNode({ input_item_ids: ['n1', 'i1'] }), items).reason).toBe('Use at most 1 input')
  })
  it('skips inputs removed from the board and judges what is left', () => {
    expect(canRun(image, makeNode({ input_item_ids: ['n1', 'gone'] }), items)).toEqual({ ok: true })
    expect(canRun(image, makeNode({ input_item_ids: ['gone'] }), items)).toEqual({ ok: false, reason: 'Add an input' })
    const two = makePlugin({ inputs: { kinds: ['image', 'note'], min: 2, max: 4 } })
    expect(canRun(two, makeNode({ input_item_ids: ['n1', 'gone'] }), items).reason).toBe('Add 1 more input')
  })
  it('is not when an input is of a kind the plugin cannot read', () => {
    const imagesOnly = makePlugin({ inputs: { kinds: ['image'], min: 1, max: 4 } })
    expect(canRun(imagesOnly, makeNode({ input_item_ids: ['i1', 'n1'] }), items)).toEqual({
      ok: false,
      reason: "Image can't read note items",
    })
  })
  it('is not when the plugin is unknown', () => {
    expect(canRun(undefined, makeNode(), items).ok).toBe(false)
  })
})

function client(nodes: NodesResponse = { nodes: [], runs: {} }) {
  const qc = new QueryClient()
  qc.setQueryData(keys.nodes('b1'), nodes)
  qc.setQueryData(keys.items('b1'), [note, photo, makeItem({ id: 'v1', kind: 'video' }), makeItem({ id: 'i2' })])
  qc.setQueryData(keys.plugins(), [image])
  return qc
}

describe('addToNode', () => {
  it('appends new ids, patches the node and is undoable', async () => {
    const node = makeNode({ input_item_ids: ['n1'] })
    const qc = client({ nodes: [node], runs: {} })
    vi.mocked(api.patchNode).mockImplementation(async (_id, body) => ({ ...node, ...body }) as never)
    expect(await addToNode(qc, 'node1', ['n1', 'i1'])).toEqual({ added: 1, notice: null })
    expect(api.patchNode).toHaveBeenCalledWith('node1', { input_item_ids: ['n1', 'i1'] })
    expect(qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes[0].input_item_ids).toEqual(['n1', 'i1'])
    expect(undoHistory.size).toBe(1)
    const entry = undoHistory.pop()
    if (entry?.kind === 'revert') entry.revert()
    expect(api.patchNode).toHaveBeenLastCalledWith('node1', { input_item_ids: ['n1'] })
  })

  it('skips items of a kind the plugin does not read, and says so', async () => {
    const node = makeNode({ input_item_ids: [] })
    const qc = client({ nodes: [node], runs: {} })
    vi.mocked(api.patchNode).mockImplementation(async (_id, body) => ({ ...node, ...body }) as never)
    expect(await addToNode(qc, 'node1', ['v1', 'i1'])).toEqual({ added: 1, notice: "Image can't read video items" })
    expect(api.patchNode).toHaveBeenCalledWith('node1', { input_item_ids: ['i1'] })
  })

  it('says when the items are already inputs, and adds nothing', async () => {
    const qc = client({ nodes: [makeNode({ input_item_ids: ['n1', 'i1'] })], runs: {} })
    expect(await addToNode(qc, 'node1', ['n1'])).toEqual({ added: 0, notice: 'That item is already an input' })
    expect(await addToNode(qc, 'node1', ['n1', 'i1'])).toEqual({ added: 0, notice: 'Those items are already inputs' })
    expect(api.patchNode).not.toHaveBeenCalled()
  })

  it('skips items missing from the cache, and adds nothing for an unknown plugin', async () => {
    const qc = client({ nodes: [makeNode({ input_item_ids: [] })], runs: {} })
    expect(await addToNode(qc, 'node1', ['nowhere'])).toEqual({ added: 0, notice: null })
    qc.setQueryData(keys.plugins(), [])
    expect(await addToNode(qc, 'node1', ['i1'])).toEqual({ added: 0, notice: 'This plugin is not loaded yet' })
    expect(api.patchNode).not.toHaveBeenCalled()
  })

  it('stops at the plugin max inputs, with a notice', async () => {
    const node = makeNode({ input_item_ids: ['n1', 'gone'] })
    const qc = client({ nodes: [node], runs: {} })
    qc.setQueryData(keys.plugins(), [makePlugin({ inputs: { kinds: ['image', 'note'], min: 1, max: 2 } })])
    vi.mocked(api.patchNode).mockImplementation(async (_id, body) => ({ ...node, ...body }) as never)
    // 'gone' is no longer on the board, so one slot is left
    expect(await addToNode(qc, 'node1', ['i1', 'i2'])).toEqual({ added: 1, notice: 'Image takes at most 2 inputs' })
    expect(api.patchNode).toHaveBeenCalledWith('node1', { input_item_ids: ['n1', 'gone', 'i1'] })
  })
})

describe('createNodeFromSelection', () => {
  it('creates a node with the accepted selected items as inputs and caches it', async () => {
    const qc = client()
    selection.select(['n1', 'v1', 'i1'])
    vi.mocked(api.createNode).mockImplementation(async (boardId, body) => makeNode({ board_id: boardId, ...body }) as never)
    const node = await createNodeFromSelection(qc, 'b1', image, { x: 10, y: 20 })
    expect(api.createNode).toHaveBeenCalledWith('b1', { plugin_id: 'image', x: 10, y: 20, input_item_ids: ['n1', 'i1'] })
    expect(node.input_item_ids).toEqual(['n1', 'i1'])
    expect(qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes.map((n) => n.id)).toEqual(['node1'])
  })
})

describe('node undo', () => {
  const undo = async () => {
    const entry = undoHistory.pop()
    if (entry?.kind === 'revert') entry.revert()
    await new Promise((r) => setTimeout(r, 0))
  }
  const ids = (qc: QueryClient) => qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes.map((n) => n.id)

  it('undo after creating a node deletes it', async () => {
    const qc = client()
    vi.mocked(api.createNode).mockImplementation(async (boardId, body) => makeNode({ board_id: boardId, ...body }) as never)
    vi.mocked(api.deleteNode).mockResolvedValue(undefined as never)
    await createNodeFromSelection(qc, 'b1', image, { x: 10, y: 20 })
    expect(undoHistory.size).toBe(1)
    await undo()
    expect(api.deleteNode).toHaveBeenCalledWith('node1')
    expect(ids(qc)).toEqual([])
    expect(undoHistory.size).toBe(0) // the undo itself is not pushed again
  })

  it('undo after removing a node recreates it with its place, live inputs and params', async () => {
    const old = makeNode({ id: 'old', x: 40, y: 50, input_item_ids: ['i1', 'gone'], params: { mode: 'whole', count: 2 } })
    const qc = client({ nodes: [old], runs: {} })
    vi.mocked(api.deleteNode).mockResolvedValue(undefined as never)
    vi.mocked(api.createNode).mockImplementation(async (boardId, body) => makeNode({ id: 'new', board_id: boardId, params: {}, ...body }) as never)
    vi.mocked(api.patchNode).mockImplementation(async (id, body) => makeNode({ id, x: 40, y: 50, input_item_ids: ['i1'], ...body }) as never)
    await removeNode(qc, 'old', { undoable: true })
    expect(ids(qc)).toEqual([])
    await undo()
    expect(api.createNode).toHaveBeenCalledWith('b1', { plugin_id: old.plugin_id, x: 40, y: 50, input_item_ids: ['i1'] })
    expect(api.patchNode).toHaveBeenCalledWith('new', { params: { mode: 'whole', count: 2 } })
    const back = qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes ?? []
    expect(back.map((n) => [n.id, n.params])).toEqual([['new', { mode: 'whole', count: 2 }]])
  })
})

describe('nodeAt', () => {
  it('finds the node under a canvas point', () => {
    const nodes = [makeNode({ id: 'a', x: 0, y: 0 }), makeNode({ id: 'b', x: 1000, y: 0 })]
    expect(nodeAt(nodes, { x: 1100, y: 50 })?.id).toBe('b')
    expect(nodeAt(nodes, { x: 700, y: 50 })).toBeNull()
  })
})
