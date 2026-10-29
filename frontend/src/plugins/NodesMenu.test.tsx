import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { keys, type NodesResponse, type PluginInfo } from '../api'
import { makeItem } from '../test/fixtures'
import { makeNode, makePlugin } from '../test/plugins'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  createNode: vi.fn(),
  patchNode: vi.fn(),
}))
const api = await import('../api')
const { NodesMenu } = await import('./NodesMenu')
const { NodeLayer } = await import('./NodeLayer')
const { sendNoteToNode, useNodeDrop } = await import('./nodeDrop')
const { selection } = await import('../canvas/selection')
const { dropTargetStore, viewportStore } = await import('./stores')

const note = makeItem({ id: 'n1', kind: 'note', note_text: 'Strap', x: 0, y: 0, w: 220, h: 96 })
const photo = makeItem({ id: 'i1', x: 300, y: 40, w: 200, h: 150 })
const video = makePlugin({ id: 'video', name: 'Video', status: 'not_connected', inputs: { kinds: ['image'], min: 1, max: 1 } })

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
  vi.mocked(api.createNode).mockImplementation(async (boardId, body) => makeNode({ id: 'new', board_id: boardId, ...body }) as never)
  vi.mocked(api.patchNode).mockImplementation(async (id, body) => makeNode({ id, ...body }) as never)
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  selection.reset()
  viewportStore.set(null)
  dropTargetStore.set(null)
})

function client(added: PluginInfo[] = [makePlugin(), video]) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.demo, { demo_mode: false, unlocked: false, plugins_enabled: true })
  qc.setQueryData(keys.plugins(), [makePlugin(), video])
  qc.setQueryData(keys.boardPlugins('b1'), added.map((p) => p.id))
  qc.setQueryData(keys.items('b1'), [note, photo])
  qc.setQueryData<NodesResponse>(keys.nodes('b1'), { nodes: [], runs: {} })
  return qc
}
const wrap = (qc: QueryClient) => ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={qc}>{children}</QueryClientProvider>
)

describe('NodesMenu', () => {
  it('lists the added plugins; choosing one places a node right of the selection with it as inputs', async () => {
    const qc = client()
    const onClose = vi.fn()
    selection.select(['n1', 'i1'])
    render(<NodesMenu boardId="b1" onClose={onClose} />, { wrapper: wrap(qc) })
    expect(screen.getByText('Not connected')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Image' }))
    expect(api.createNode).toHaveBeenCalledWith('b1', { plugin_id: 'image', x: 548, y: 0, input_item_ids: ['n1', 'i1'] })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes.map((n) => n.id)).toEqual(['new'])
  })

  it('with nothing selected the node goes to the middle of the view', () => {
    const qc = client()
    viewportStore.set({ view: { x: 0, y: 0, scale: 1 }, width: 1000, height: 800 })
    render(<NodesMenu boardId="b1" onClose={vi.fn()} />, { wrapper: wrap(qc) })
    fireEvent.click(screen.getByRole('button', { name: 'Image' }))
    expect(api.createNode).toHaveBeenCalledWith('b1', { plugin_id: 'image', x: 350, y: 220, input_item_ids: [] })
  })

  it('points to the Plugins panel when the board has none', () => {
    render(<NodesMenu boardId="b1" onClose={vi.fn()} />, { wrapper: wrap(client([])) })
    expect(screen.getByRole('button', { name: 'Open Plugins' })).toBeTruthy()
  })
})

describe('sendNoteToNode', () => {
  it('creates a node beside the note with the note as its input', async () => {
    const qc = client()
    await sendNoteToNode(qc, 'b1', 'image', 'n1')
    expect(api.createNode).toHaveBeenCalledWith('b1', { plugin_id: 'image', x: 268, y: 0, input_item_ids: ['n1'] })
  })
})

describe('useNodeDrop', () => {
  it('marks the node under the pointer and adds the dropped items to it', async () => {
    const qc = client()
    qc.setQueryData<NodesResponse>(keys.nodes('b1'), { nodes: [makeNode({ x: 1000, y: 0, input_item_ids: [] })], runs: {} })
    const { result } = renderHook(() => useNodeDrop('b1'), { wrapper: wrap(qc) })
    act(() => result.current.hover({ x: 1100, y: 100 }))
    expect(dropTargetStore.get()).toBe('node1')
    expect(result.current.drop({ x: 0, y: 0 }, ['i1'])).toBe(false)
    expect(result.current.drop({ x: 1100, y: 100 }, ['i1', 'n1'])).toBe(true)
    expect(dropTargetStore.get()).toBeNull()
    expect(api.patchNode).toHaveBeenCalledWith('node1', { input_item_ids: ['i1', 'n1'] })
  })

  it('does nothing on a read-only board', () => {
    const qc = client()
    qc.setQueryData<NodesResponse>(keys.nodes('b1'), { nodes: [makeNode({ x: 0, y: 0 })], runs: {} })
    const { result } = renderHook(() => useNodeDrop('b1', true), { wrapper: wrap(qc) })
    expect(result.current.drop({ x: 10, y: 10 }, ['i1'])).toBe(false)
    expect(api.patchNode).not.toHaveBeenCalled()
  })
})

describe('NodeLayer', () => {
  it('draws each node as a card with lines from its inputs, and publishes the viewport', () => {
    const qc = client()
    qc.setQueryData<NodesResponse>(keys.nodes('b1'), { nodes: [makeNode({ x: 1000, input_item_ids: ['i1', 'gone'] })], runs: {} })
    render(<NodeLayer boardId="b1" items={[note, photo]} view={{ x: 0, y: 0, scale: 0.5 }} size={{ width: 800, height: 600 }} />, {
      wrapper: wrap(qc),
    })
    const card = screen.getByRole('group', { name: 'Image node' }) as HTMLElement
    expect(card.style.left).toBe('500px')
    expect(card.style.transform).toBe('scale(0.5)')
    expect(document.querySelectorAll('.node-lines path')).toHaveLength(1) // the removed input has no line
    expect(screen.getByRole('button', { name: 'Remove input removed item' })).toBeTruthy()
    expect(viewportStore.get()).toEqual({ view: { x: 0, y: 0, scale: 0.5 }, width: 800, height: 600 })
  })

  it('renders nothing while plugins are off', () => {
    const qc = client()
    qc.setQueryData(keys.demo, { demo_mode: false, unlocked: false, plugins_enabled: false })
    qc.setQueryData<NodesResponse>(keys.nodes('b1'), { nodes: [makeNode()], runs: {} })
    render(<NodeLayer boardId="b1" items={[]} view={{ x: 0, y: 0, scale: 1 }} size={{ width: 800, height: 600 }} />, { wrapper: wrap(qc) })
    expect(screen.queryByRole('group')).toBeNull()
  })
})
