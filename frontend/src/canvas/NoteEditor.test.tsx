import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import KonvaLib from 'konva'
import type Konva from 'konva'
import { type Item, keys, type PluginInfo } from '../api'
import { noteVisualizeStore } from '../events'
import { isTyping } from '../pages/shortcutGuard'
import { BoardShell } from '../shell/BoardShell'
import { setTool, toolStore } from '../shell/tools'
import { stubCanvasContext } from '../test/canvasStub'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  createNote: vi.fn(),
  patchItem: vi.fn(() => Promise.resolve({})),
  deleteItem: vi.fn(() => Promise.resolve()),
  visualizeNote: vi.fn(() => Promise.resolve({ note_id: 'n1', status: 'visualizing' })),
}))
const api = await import('../api')
const { useItemActions } = await import('./actions')
const { Canvas } = await import('./Canvas')
const { undoHistory } = await import('./history')
const { selection } = await import('./selection')

type Actions = ReturnType<typeof useItemActions>

const note = (over: Partial<Item> = {}) =>
  makeItem({
    id: 'n1', board_id: 'b1', kind: 'note', origin: 'note', note_text: 'Strap in waxed canvas',
    x: 0, y: 0, w: 220, h: 96, sha256: null, mime: null, storage_path: null, thumb_path: null, ...over,
  })

beforeEach(() => {
  stubCanvasContext()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ demo_mode: false }), { status: 200 }))
  vi.mocked(api.createNote).mockImplementation(async (boardId, body) =>
    note({ id: 'new1', board_id: boardId, note_text: body.text, x: body.x, y: body.y, w: body.w ?? 220, h: body.h ?? 96 }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  undoHistory.clear()
  selection.reset()
  setTool('select')
  noteVisualizeStore.set({ ids: new Set() })
})

function setup(opts: { items?: Item[]; locked?: boolean; shell?: boolean; plugins?: PluginInfo[]; onSendToNode?: (p: string, n: string) => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.demo, { demo_mode: !!opts.locked, unlocked: false, plugins_enabled: !!opts.plugins })
  if (opts.plugins) {
    qc.setQueryData(keys.plugins(), opts.plugins)
    qc.setQueryData(keys.boardPlugins('b1'), opts.plugins.map((p) => p.id))
  }
  qc.setQueryData(keys.explorations('b1'), [])
  qc.setQueryData(keys.lens('b1'), null)
  qc.setQueryData(keys.items('b1'), opts.items ?? [])
  const out: { actions: Actions | null } = { actions: null }
  function Harness() {
    const actions = useItemActions('b1')
    useEffect(() => {
      out.actions = actions
    })
    const items = useQuery<Item[]>({ queryKey: keys.items('b1'), queryFn: () => [] }).data ?? []
    return (
      <Canvas
        boardId="b1"
        items={items}
        actions={actions}
        onFiles={vi.fn()}
        onOpenPanel={vi.fn()}
        spaceDown={false}
        readOnly={!!opts.locked}
        onSendToNode={opts.onSendToNode}
      />
    )
  }
  const view = render(
    <QueryClientProvider client={qc}>
      {opts.shell ? (
        <BoardShell
          boardId="b1"
          items={[]}
          header={null}
          canvas={<Harness />}
          onFocusItem={vi.fn()}
          onFindExamples={vi.fn()}
          plugins={false}
          explore
        />
      ) : (
        <Harness />
      )}
    </QueryClientProvider>,
  )
  const stage = () => view.container.querySelector('.konvajs-content') as HTMLElement
  const clickStage = (x: number, y: number) => fireEvent.mouseDown(stage(), { clientX: x, clientY: y, button: 0 })
  const items = () => qc.getQueryData<Item[]>(keys.items('b1')) ?? []
  return { qc, out, view, clickStage, items }
}

const editor = () => screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement

describe('placing a note', () => {
  it('note tool click opens the editor there; typing then Esc creates the note at those canvas coords', async () => {
    const { clickStage, items } = setup()
    act(() => setTool('note'))
    clickStage(300, 200) // view starts at (80, 80), scale 1
    const box = editor()
    expect(document.activeElement).toBe(box)
    expect(box.style.left).toBe('300px')
    expect(box.style.top).toBe('200px')
    expect(toolStore.get()).toBe('select')
    fireEvent.change(box, { target: { value: 'Strap in waxed canvas' } })
    fireEvent.keyDown(box, { key: 'Escape' })
    expect(screen.queryByRole('textbox', { name: 'Note' })).toBeNull()
    expect(api.createNote).toHaveBeenCalledWith(
      'b1',
      expect.objectContaining({ text: 'Strap in waxed canvas', x: 220, y: 120, w: 220 }),
    )
    await waitFor(() => expect(items().map((i) => i.id)).toEqual(['new1']))
  })

  it('blur saves too', async () => {
    const { clickStage } = setup()
    act(() => setTool('note'))
    clickStage(300, 200)
    fireEvent.change(editor(), { target: { value: 'Dark olive' } })
    fireEvent.blur(editor())
    expect(api.createNote).toHaveBeenCalledOnce()
  })

  it('an empty new note is discarded without residue', () => {
    const { clickStage, items } = setup()
    act(() => setTool('note'))
    clickStage(300, 200)
    fireEvent.change(editor(), { target: { value: '   ' } })
    fireEvent.keyDown(editor(), { key: 'Escape' })
    expect(screen.queryByRole('textbox', { name: 'Note' })).toBeNull()
    expect(api.createNote).not.toHaveBeenCalled()
    expect(api.deleteItem).not.toHaveBeenCalled()
    expect(items()).toEqual([])
    expect(undoHistory.size).toBe(0)
  })

  it('undo after create removes the note', async () => {
    const { clickStage, items, out } = setup()
    act(() => setTool('note'))
    clickStage(300, 200)
    fireEvent.change(editor(), { target: { value: 'Strap' } })
    fireEvent.keyDown(editor(), { key: 'Escape' })
    await waitFor(() => expect(items()).toHaveLength(1))
    act(() => {
      out.actions!.undo()
    })
    expect(items()).toEqual([])
    expect(api.deleteItem).toHaveBeenCalledWith('new1')
  })

  it('does not place a note on a locked demo', () => {
    const { clickStage } = setup({ locked: true })
    act(() => setTool('note'))
    clickStage(300, 200)
    expect(screen.queryByRole('textbox', { name: 'Note' })).toBeNull()
  })

  it('typing n, a or Delete inside the editor neither switches tools nor deletes', () => {
    const { clickStage } = setup({ shell: true, items: [note()] })
    act(() => selection.select(['n1']))
    act(() => setTool('note'))
    clickStage(500, 400)
    const box = editor()
    const reached: KeyboardEvent[] = []
    const spy = (e: KeyboardEvent) => reached.push(e)
    window.addEventListener('keydown', spy)
    for (const key of ['n', 'a', 'Delete', 'Backspace']) fireEvent.keyDown(box, { key })
    window.removeEventListener('keydown', spy)
    expect(toolStore.get()).toBe('select')
    expect(api.deleteItem).not.toHaveBeenCalled()
    // the board's own handlers (BoardPage) skip keys typed into a field
    expect(reached.every((e) => isTyping(e.target))).toBe(true)
    expect(box.isConnected).toBe(true)
  })
})

describe('editing a note', () => {
  it('Edit text, type, Esc saves note_text', () => {
    const { items } = setup({ items: [note()] })
    act(() => selection.select(['n1']))
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit text' }))
    const box = editor()
    expect(box.value).toBe('Strap in waxed canvas')
    fireEvent.change(box, { target: { value: 'Strap in olive canvas' } })
    fireEvent.keyDown(box, { key: 'Escape' })
    expect(api.patchItem).toHaveBeenCalledWith('n1', expect.objectContaining({ note_text: 'Strap in olive canvas' }))
    expect(items()[0].note_text).toBe('Strap in olive canvas')
  })

  it('an emptied edit restores the old text', () => {
    const { items } = setup({ items: [note()] })
    act(() => selection.select(['n1']))
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit text' }))
    fireEvent.change(editor(), { target: { value: '' } })
    fireEvent.keyDown(editor(), { key: 'Escape' })
    expect(api.patchItem).not.toHaveBeenCalled()
    expect(items()[0].note_text).toBe('Strap in waxed canvas')
  })

  it('undo after an edit puts the old text back', () => {
    const { items, out } = setup({ items: [note()] })
    act(() => selection.select(['n1']))
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit text' }))
    fireEvent.change(editor(), { target: { value: 'New text' } })
    fireEvent.keyDown(editor(), { key: 'Escape' })
    act(() => {
      out.actions!.undo()
    })
    expect(items()[0].note_text).toBe('Strap in waxed canvas')
    expect(api.patchItem).toHaveBeenLastCalledWith('n1', expect.objectContaining({ note_text: 'Strap in waxed canvas' }))
  })

  it('Delete in the menu removes the note', () => {
    const { items } = setup({ items: [note()] })
    act(() => selection.select(['n1']))
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(api.deleteItem).toHaveBeenCalledWith('n1')
    expect(items()).toEqual([])
  })
})

describe('note bar and Visualize', () => {
  it('Visualize is disabled when the note has no text', () => {
    setup({ items: [note({ note_text: '' })] })
    act(() => selection.select(['n1']))
    expect((screen.getByRole('button', { name: /Visualize/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('Visualize is disabled on a locked demo', () => {
    setup({ items: [note()], locked: true })
    act(() => selection.select(['n1']))
    expect((screen.getByRole('button', { name: /Visualize/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('Visualize calls visualizeNote and shows the placeholder beside the note', async () => {
    setup({ items: [note({ x: 10, y: 20 })] })
    act(() => selection.select(['n1']))
    const bar = screen.getByRole('toolbar', { name: 'Note actions' })
    fireEvent.click(within(bar).getByRole('button', { name: /Visualize/ }))
    expect(api.visualizeNote).toHaveBeenCalledWith('n1')
    expect((within(bar).getByRole('button', { name: /Visualizing/ }) as HTMLButtonElement).disabled).toBe(true)
    const stage = KonvaLib.stages.at(-1)!
    const card = stage.findOne<Konva.Group>('.note-placeholder')!
    expect(card).toBeTruthy()
    expect({ x: card.x(), y: card.y() }).toEqual({ x: 10 + 220 + 40, y: 20 })
    expect(stage.findOne<Konva.Line>('.note-placeholder-line')!.dash().length).toBeGreaterThan(0)
  })

  it('a generated image from a note gets a solid line to it; staged items are not drawn', async () => {
    const child = makeItem({ id: 'g1', board_id: 'b1', origin: 'generated', parent_item_id: 'n1', x: 300, y: 0 })
    const staged = makeItem({ id: 's1', board_id: 'b1', staged: true })
    setup({ items: [note(), child, staged] })
    const stage = KonvaLib.stages.at(-1)!
    const line = stage.findOne<Konva.Line>('.note-lineage')!
    expect(line).toBeTruthy()
    expect(line.dash() ?? []).toEqual([])
    expect(stage.findOne('#s1')).toBeUndefined()
    expect(stage.findOne('#g1')).toBeTruthy()
  })

  it('⋯ lists the plugins on the board that take notes, under Send to node', () => {
    const plugin = (id: string, kinds: string[]) =>
      ({ id, name: `Plugin ${id}`, inputs: { kinds, min: 1, max: 1 } }) as unknown as PluginInfo
    const onSendToNode = vi.fn()
    setup({ items: [note()], plugins: [plugin('p1', ['note']), plugin('p2', ['image'])], onSendToNode })
    act(() => selection.select(['n1']))
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    const group = screen.getByRole('group', { name: 'Send to node' })
    expect(within(group).getAllByRole('menuitem').map((b) => b.textContent)).toEqual(['Plugin p1'])
    fireEvent.click(within(group).getByRole('menuitem', { name: 'Plugin p1' }))
    expect(onSendToNode).toHaveBeenCalledWith('p1', 'n1')
  })

  it('hides Send to node when plugins are off', () => {
    setup({ items: [note()], onSendToNode: vi.fn() })
    act(() => selection.select(['n1']))
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
    expect(screen.queryByRole('group', { name: 'Send to node' })).toBeNull()
  })
})
