import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type Item, keys, type NodesResponse, type PluginInfo, type PluginNode, type PluginRun } from '../api'
import { useNodes } from '../queries'
import { BoardShell } from '../shell/BoardShell'
import { setTool, toolStore } from '../shell/tools'
import { makeItem } from '../test/fixtures'
import { makeNode, makePlugin, makePluginRun } from '../test/plugins'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  runNode: vi.fn(),
  patchNode: vi.fn(),
  deleteNode: vi.fn(() => Promise.resolve()),
  listNodes: vi.fn(() => new Promise(() => {})),
}))
const api = await import('../api')
const { NodeCard } = await import('./NodeCard')
const { undoHistory } = await import('../canvas/history')

const note = makeItem({ id: 'n1', kind: 'note', note_text: 'Strap in waxed canvas', thumb_path: null })
const photo = makeItem({ id: 'i1', original_filename: 'watch.png' })
const items = new Map<string, Item>([
  [note.id, note],
  [photo.id, photo],
])

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ demo_mode: false }), { status: 200 }))
  vi.mocked(api.patchNode).mockImplementation(async (id, body) => makeNode({ id, ...body }) as never)
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  undoHistory.clear()
  setTool('select')
})

interface Opts {
  plugin?: PluginInfo
  node?: PluginNode
  run?: PluginRun
  readOnly?: boolean
  wrap?: (card: ReactNode) => ReactNode
}

function setup(opts: Opts = {}) {
  const plugin = opts.plugin ?? makePlugin()
  const node = opts.node ?? makeNode({ input_item_ids: ['i1', 'n1'], last_run_id: opts.run?.id ?? null })
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.demo, { demo_mode: false, unlocked: false, plugins_enabled: true })
  qc.setQueryData(keys.plugins(), [plugin])
  qc.setQueryData(keys.boardPlugins('b1'), [plugin.id])
  qc.setQueryData(keys.items('b1'), [...items.values()])
  qc.setQueryData<NodesResponse>(keys.nodes('b1'), { nodes: [node], runs: opts.run ? { [node.id]: opts.run } : {} })
  function Live() {
    const data = useNodes('b1').data
    const n = data?.nodes.find((x) => x.id === node.id) ?? node
    return <NodeCard boardId="b1" node={n} plugin={plugin} run={data?.runs[n.id]} items={items} view={{ x: 0, y: 0, scale: 1 }} readOnly={opts.readOnly} />
  }
  const card = <Live />
  render(<QueryClientProvider client={qc}>{opts.wrap ? opts.wrap(card) : card}</QueryClientProvider>)
  return { qc, node }
}

const runButton = () => screen.getByRole('button', { name: /^Run/ }) as HTMLButtonElement

describe('NodeCard', () => {
  it('shows the header, input chips and the settings line', () => {
    setup()
    const card = screen.getByRole('group', { name: 'Image node' })
    expect(within(card).getByText('Image')).toBeTruthy()
    expect(within(card).getByText('Muse Spark')).toBeTruthy()
    expect(within(card).getByRole('button', { name: 'Remove input watch.png' })).toBeTruthy()
    expect(within(card).getByRole('button', { name: 'Remove input Strap in waxed canvas' })).toBeTruthy()
    expect(within(card).getByText('Change only a part')).toBeTruthy()
    expect(runButton().textContent).toBe('Run')
  })

  it('Run calls runNode and caches the run', async () => {
    const { qc } = setup()
    vi.mocked(api.runNode).mockResolvedValue(makePluginRun({ id: 'r9' }))
    fireEvent.click(runButton())
    expect(api.runNode).toHaveBeenCalledWith('node1')
    await waitFor(() => expect(qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.runs.node1?.id).toBe('r9'))
    expect(qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes[0].last_run_id).toBe('r9')
  })

  it('running shows the progress and disables Run', () => {
    setup({ run: makePluginRun({ status: 'running', progress: { message: 'Masking the dial' } }) })
    expect(screen.getByRole('progressbar')).toBeTruthy()
    expect(screen.getByText('Masking the dial')).toBeTruthy()
    expect(runButton().disabled).toBe(true)
  })

  it('a 409 NODE_RUNNING is treated as running', async () => {
    setup()
    vi.mocked(api.runNode).mockRejectedValue(new ApiError(409, 'NODE_RUNNING', 'This node is already running'))
    fireEvent.click(runButton())
    await waitFor(() => expect(screen.getByRole('progressbar')).toBeTruthy())
    expect(runButton().disabled).toBe(true)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a 400 from Run is shown in plain words', async () => {
    setup()
    vi.mocked(api.runNode).mockRejectedValue(new ApiError(400, 'PLUGIN_BAD_INPUT', 'Image needs an image or a note'))
    fireEvent.click(runButton())
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Image needs an image or a note'))
    expect(runButton().disabled).toBe(false)
  })

  it('failed shows the message and enables Run again', () => {
    setup({ run: makePluginRun({ status: 'failed', error_code: 'PLUGIN_CRASHED', error_message: 'The model timed out' }) })
    expect(screen.getByRole('alert').textContent).toContain('The model timed out')
    expect(runButton().textContent).toBe('Run again')
    expect(runButton().disabled).toBe(false)
  })

  it('done shows the generated items and the text output', () => {
    const made = makeItem({ id: 'g1', origin: 'generated', original_filename: 'image.png' })
    items.set('g1', made)
    setup({ run: makePluginRun({ status: 'done', output: { text: 'Two swatches found', created_item_ids: ['g1'] } }) })
    expect(screen.getByText('Two swatches found')).toBeTruthy()
    expect(document.querySelector('.node-output img')).toBeTruthy()
    expect(runButton().textContent).toBe('Run again')
    items.delete('g1')
  })

  it('removing an input chip calls patchNode with the rest', async () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Remove input watch.png' }))
    expect(api.patchNode).toHaveBeenCalledWith('node1', { input_item_ids: ['n1'] })
  })

  it('a placeholder plugin shows not connected and a disabled Run', () => {
    setup({ plugin: makePlugin({ id: 'video', name: 'Video', runs_on: '[video model]', status: 'not_connected', secondary: 'Track with SAM' }) })
    expect(screen.getByText('[video model] not connected')).toBeTruthy()
    expect(runButton().disabled).toBe(true)
    expect(screen.getByRole('button', { name: 'Track with SAM' })).toBeTruthy()
  })

  it('Run is disabled with the reason when there are no inputs', () => {
    setup({ node: makeNode({ input_item_ids: [] }) })
    expect(runButton().disabled).toBe(true)
    expect(screen.getByText('Add an input')).toBeTruthy()
  })

  it('the settings line opens the param fields; x-show-if hides part for the whole image', async () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: /Change only a part/ }))
    expect(screen.getByLabelText('Part')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'whole' } })
    expect(api.patchNode).toHaveBeenCalledWith('node1', { params: { mode: 'whole' } })
    await waitFor(() => expect(screen.queryByLabelText('Part')).toBeNull())
  })

  it('a text param is saved on blur', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Prompt' })) // the secondary button opens the settings
    const part = screen.getByLabelText('Part')
    fireEvent.change(part, { target: { value: 'dial' } })
    expect(api.patchNode).not.toHaveBeenCalled()
    fireEvent.blur(part)
    expect(api.patchNode).toHaveBeenCalledWith('node1', { params: { part: 'dial' } })
  })

  it('typing in a param field does not trigger tool shortcuts', () => {
    setup({
      wrap: (card) => (
        <BoardShell boardId="b1" items={[]} header={null} canvas={card} onFocusItem={vi.fn()} onFindExamples={vi.fn()} plugins explore />
      ),
    })
    fireEvent.click(screen.getByRole('button', { name: /Change only a part/ }))
    const part = screen.getByLabelText('Part')
    part.focus()
    fireEvent.keyDown(part, { key: 'n' })
    fireEvent.keyDown(part, { key: 'a' })
    expect(toolStore.get()).toBe('select')
    fireEvent.keyDown(document.body, { key: 'n' }) // the guard, not a dead listener
    expect(toolStore.get()).toBe('note')
  })

  it('More actions → Remove node deletes it', async () => {
    const { qc } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove node' }))
    expect(api.deleteNode).toHaveBeenCalledWith('node1')
    expect(qc.getQueryData<NodesResponse>(keys.nodes('b1'))?.nodes).toEqual([])
  })

  it('dragging the header moves the node, undoably', async () => {
    setup()
    const head = document.querySelector('.node-head') as HTMLElement
    fireEvent.pointerDown(head, { clientX: 10, clientY: 10, button: 0 })
    fireEvent.pointerMove(window, { clientX: 60, clientY: 30 })
    fireEvent.pointerUp(window, { clientX: 60, clientY: 30 })
    expect(api.patchNode).toHaveBeenCalledWith('node1', { x: 450, y: 20 })
    expect(undoHistory.size).toBe(1)
    const entry = undoHistory.pop()
    if (entry?.kind === 'revert') entry.revert()
    expect(api.patchNode).toHaveBeenLastCalledWith('node1', { x: 400, y: 0 })
  })

  it('a read-only board cannot run or edit', () => {
    setup({ readOnly: true })
    expect(runButton().disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Remove input watch.png' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
