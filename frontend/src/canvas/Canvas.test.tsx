import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import Konva from 'konva'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AnalysisView, type Exploration, type ExploreOption, type Item, keys } from '../api'
import '../panels/registerPanels'
import { stubCanvasContext } from '../test/canvasStub'
import { makeItem } from '../test/fixtures'
import { selection } from './selection'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  getRegion: vi.fn(() => Promise.resolve({ kind: 'mask', box: [0.4, 0.2, 0.6, 0.5], mask_url: '/api/media/masks/hands.png' })),
  exploreItem: vi.fn(),
  visualizeOption: vi.fn(),
  patchItem: vi.fn(() => Promise.resolve({})),
  patchOption: vi.fn(() => Promise.resolve({})),
  getRenderers: vi.fn(() => Promise.resolve([])),
}))
const { getRegion, exploreItem, visualizeOption, patchItem, patchOption } = await import('../api')
const { setCollapsed } = await import('../map/collapse')
const { useItemActions } = await import('./actions')
const { Canvas } = await import('./Canvas')
const { undoHistory } = await import('./history')

const translateOf = (el: HTMLElement) => {
  const m = /translate\(([-\d.e]+)px, ([-\d.e]+)px\)/.exec(el.style.transform)!
  return { x: parseFloat(m[1]), y: parseFloat(m[2]) }
}

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`,
    description: '', distance: 'near', value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null, undocked: false,
    ...over,
  }
}

function client(explorations: Exploration[], items: Item[], explore = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  qc.setQueryData(keys.demo, { demo_mode: false, explore_enabled: explore })
  qc.setQueryData(keys.explorations('b1'), explorations)
  qc.setQueryData(keys.items('b1'), items)
  return qc
}

let boardActions: ReturnType<typeof useItemActions> | null = null
/** The board page in small: the canvas over the cached items, with the real item actions. */
function Board({ onOpenPanel = vi.fn() }: { onOpenPanel?: (...args: unknown[]) => void }) {
  const items = useQuery<Item[]>({ queryKey: keys.items('b1'), queryFn: () => [] }).data ?? []
  const actions = useItemActions('b1')
  useEffect(() => {
    boardActions = actions
  })
  return <Canvas boardId="b1" items={items} actions={actions} onFiles={vi.fn()} onOpenPanel={onOpenPanel} spaceDown={false} />
}

function renderBoard(qc: QueryClient, onOpenPanel?: (...args: unknown[]) => void) {
  return render(
    <QueryClientProvider client={qc}>
      <Board onOpenPanel={onOpenPanel} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  selection.clear()
  undoHistory.clear()
  localStorage.clear()
})

describe('Canvas flowers', () => {
  const analysis: AnalysisView = {
    content_type: 'image',
    parse_status: 'completed',
    parts: [{ key: 'hands', label: 'Hands', region_kind: 'box', region: [0.8, 0.4, 0.9, 0.6], mask_url: null, source: 'ai' }],
    dimensions: [
      { key: 'hand_style', label: 'Hand style', type: 'physical', part: 'hands', prompt: null, kind: 'enum', value: 'syringe', confidence: 0.9, source: 'ai', status: 'extracted' },
    ],
  }
  /** A real-sized canvas, so the stage draws and flowers reach the viewport. */
  const sized = () => {
    stubCanvasContext()
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1600)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(1200)
  }

  it('clicking a dimension opens a hub with note petals and generates nothing', async () => {
    sized()
    const e: Exploration = { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' }), opt({ id: 'o2', name: 'Ember' })] }
    vi.mocked(exploreItem).mockResolvedValue(e)
    const qc = client([], [makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })])
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    act(() => selection.select(['src']))
    fireEvent.click(screen.getByRole('button', { name: 'Hand style · syringe' }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('src', { key: 'hand_style', mode: 'initial' }))
    const flower = await screen.findByRole('group', { name: 'Hand style flower' })
    expect(within(flower).getByText('2 options · 0 kept')).toBeTruthy()
    const petals = within(flower).getAllByTestId('petal')
    expect(petals.map((p) => p.className)).toEqual(['petal is-note', 'petal is-note'])
    expect(visualizeOption).not.toHaveBeenCalled()
  })

  it('clicking a dimension that already has a flower opens it again without exploring', async () => {
    sized()
    setCollapsed('b1', 'e1', true)
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
      [makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    expect(screen.getByRole('button', { name: 'Hand style · 1 options · 0 kept' })).toBeTruthy() // the badge
    act(() => selection.select(['src']))
    fireEvent.click(screen.getByRole('button', { name: 'Hand style · syringe' }))
    await waitFor(() => expect(screen.getAllByTestId('petal')).toHaveLength(1))
    expect(exploreItem).not.toHaveBeenCalled()
  })

  it('re-opening a flower out of sight pans it into view', async () => {
    sized()
    // view starts at (80, 80): an item at x 1300 has its flower past the right edge
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
      [makeItem({ id: 'src', board_id: 'b1', x: 1300, y: 0 })],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    const stage = Konva.stages.at(-1)!
    expect(stage.x()).toBe(80)
    act(() => selection.select(['src']))
    fireEvent.click(screen.getByRole('button', { name: 'Hand style · syringe' }))
    // at once (the board's first fit, 300 ms after load, must not be what moves it)
    expect(stage.x()).not.toBe(80)
    // the flower now sits inside the viewport
    const hub = document.querySelector<HTMLElement>('.flower-hub')!
    const left = translateOf(hub).x * stage.scaleX() + stage.x()
    expect(left).toBeGreaterThan(0)
    expect(left + parseFloat(hub.style.width) * stage.scaleX()).toBeLessThan(1600)
    expect(exploreItem).not.toHaveBeenCalled()
  })

  const stems = () => document.querySelectorAll('path[data-edge-kind="stem"]')

  it('flowers stay connected when nothing is selected', () => {
    sized()
    const qc = client(
      [
        { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' }), opt({ id: 'o2' })] },
        { id: 'e2', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'other', options: [opt({ id: 'o3', exploration_id: 'e2' })] },
      ],
      [makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    expect(document.querySelectorAll('.flower-hub')).toHaveLength(2)
    expect(stems()).toHaveLength(2)
    expect([...stems()].map((p) => p.getAttribute('data-edge-id')).sort()).toEqual(['stem:e1', 'stem:e2'])
    expect(document.querySelectorAll('path[data-edge-kind="spoke"]')).toHaveLength(3)
  })

  it('a selected item keeps one stem per flower, from its callout', () => {
    sized()
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
      [makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    act(() => selection.select(['src']))
    expect(screen.getByRole('group', { name: 'Hands' })).toBeTruthy()
    expect(stems()).toHaveLength(1)
  })

  it('a hub, its petals and the callouts are placed by the world (a transform), not left/top', () => {
    sized()
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
      [makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    act(() => selection.select(['src']))
    for (const el of [document.querySelector<HTMLElement>('.flower-hub')!, screen.getAllByTestId('petal')[0], screen.getByRole('group', { name: 'Hands' })]) {
      expect(el.style.transform).toMatch(/^translate\(/)
      expect(el.style.left).toBe('')
    }
  })

  it('draws no flowers when explore is off', () => {
    sized()
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
      [makeItem({ id: 'src', board_id: 'b1' })],
      false,
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    expect(screen.queryAllByTestId('petal')).toEqual([])
  })

  it('a kept take is an ordinary item on the board, docked in its ring', () => {
    sized()
    const src = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })
    const kept = makeItem({ id: 'k1', board_id: 'b1', x: 700, y: 0, original_filename: 'Honey.png', explore_option_id: 'o1', origin: 'generated', parent_item_id: 'src' })
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', name: 'Honey', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
      [src, kept],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    // drawn on the stage and listed like any item
    const node = Konva.stages.at(-1)!.findOne('#k1')!
    expect(node.visible()).toBe(true)
    expect(screen.getByRole('list', { name: 'Items on this board' }).textContent).toContain('Honey.png')
    // it stands in for its petal, tied to the hub by a kept spoke
    expect(document.querySelector('[data-option-id="o1"]')).toBeNull()
    expect(document.querySelector('path[data-edge-id="spoke:o1"]')!.classList.contains('is-kept')).toBe(true)
  })

  it('a kept result gets its own callouts when selected', () => {
    sized()
    const src = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })
    const kept = makeItem({ id: 'k1', board_id: 'b1', x: 700, y: 0, explore_option_id: 'o1', origin: 'generated', parent_item_id: 'src' })
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
      [src, kept],
    )
    qc.setQueryData(keys.analysis('k1'), analysis)
    renderBoard(qc)
    act(() => selection.select(['k1']))
    expect(screen.getByRole('group', { name: 'Hands' })).toBeTruthy()
  })
})

describe('Canvas item drag', () => {
  const sized = () => {
    stubCanvasContext()
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1600)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(1200)
  }
  const drag = (node: Konva.Node, dx: number, dy: number) => {
    const start = node.position()
    const evt = new MouseEvent('mousemove')
    act(() => {
      node.fire('dragstart', { evt })
      node.position({ x: start.x + dx / 2, y: start.y + dy / 2 })
      node.fire('dragmove', { evt })
      node.position({ x: start.x + dx, y: start.y + dy })
      node.fire('dragmove', { evt })
      node.fire('dragend', { evt })
    })
  }

  it('a drag saves the released spot once, and undo moves the item back', async () => {
    sized()
    const qc = client([], [makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 }), makeItem({ id: 'far', board_id: 'b1', x: 2000, y: 0 })])
    renderBoard(qc)
    const node = Konva.stages.at(-1)!.findOne('#src')!
    drag(node, 100, 50)
    expect(patchItem).toHaveBeenCalledTimes(1)
    expect(patchItem).toHaveBeenCalledWith('src', { x: 100, y: 50 })
    expect(qc.getQueryData<Item[]>(keys.items('b1'))!.find((i) => i.id === 'src')).toMatchObject({ x: 100, y: 50 })
    // the dragged item is selected (pinned): its toolbar sits over where it was dropped (view at 80, 80)
    const toolbar = screen.getByRole('toolbar', { name: 'Item actions' })
    await waitFor(() => expect(toolbar.style.left).toBe('280px'))
    // undo puts it back, and the pinned body goes with it
    act(() => void boardActions!.undo())
    expect(patchItem).toHaveBeenLastCalledWith('src', { x: 0, y: 0 })
    await waitFor(() => expect(toolbar.style.left).toBe('180px'))
  })

  it('dragging a docked take out of its ring undocks it at full size, as one undo step', () => {
    sized()
    const src = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })
    const kept = makeItem({ id: 'k1', board_id: 'b1', x: 700, y: 0, w: 168, h: 105, explore_option_id: 'o1', origin: 'generated' })
    const qc = client(
      [{ id: 'e1', board_id: 'b1', dx: 300, dy: 0, item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
      [src, kept],
    )
    renderBoard(qc)
    drag(Konva.stages.at(-1)!.findOne('#k1')!, 1200, 0)
    expect(patchOption).toHaveBeenCalledWith('o1', { undocked: true })
    expect(vi.mocked(patchItem).mock.calls.find(([id]) => id === 'k1')?.[1]).toMatchObject({ w: 300, h: 187.5 })
    expect(qc.getQueryData<Exploration[]>(keys.explorations('b1'))![0].options[0].undocked).toBe(true)
    expect(undoHistory.size).toBe(1)
  })
})

describe('Canvas part callouts', () => {
  const analysis: AnalysisView = {
    content_type: 'image',
    parse_status: 'completed',
    parts: [{ key: 'hands', label: 'Hands', region_kind: 'mask', region: null, mask_url: null, source: 'ai' }],
    dimensions: [
      { key: 'hand_style', label: 'Hand style', type: 'physical', part: 'hands', prompt: null, kind: 'enum', value: 'syringe', confidence: 0.9, source: 'ai', status: 'extracted' },
    ],
  }

  it('hovering a callout requests its region and shows the overlay', async () => {
    const qc = client([], [makeItem({ id: 'src', board_id: 'b1' })])
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    expect(screen.queryByRole('group', { name: 'Hands' })).toBeNull()
    act(() => selection.select(['src']))
    const hands = screen.getByRole('group', { name: 'Hands' })
    expect(screen.queryByTestId('region-overlay')).toBeNull()
    fireEvent.mouseEnter(hands)
    expect(getRegion).toHaveBeenCalledWith('src', 'hands')
    // while SAM looks for the part: a dashed outline
    expect(screen.getByTestId('region-overlay').dataset.state).toBe('loading')
    await waitFor(() => expect(screen.getByTestId('region-overlay').dataset.state).toBe('mask'))
    fireEvent.mouseLeave(hands)
    expect(screen.queryByTestId('region-overlay')).toBeNull()
  })

  it('deselecting while a part is hovered clears it: selecting again shows no region', async () => {
    const qc = client([], [makeItem({ id: 'src', board_id: 'b1' })])
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    act(() => selection.select(['src']))
    fireEvent.mouseEnter(screen.getByRole('group', { name: 'Hands' }))
    await waitFor(() => expect(screen.getByTestId('region-overlay').dataset.state).toBe('mask'))
    act(() => selection.clear()) // e.g. Escape; the mouse never left the card
    expect(screen.queryByTestId('region-overlay')).toBeNull()
    act(() => selection.select(['src']))
    expect(screen.getByRole('group', { name: 'Hands' })).toBeTruthy()
    expect(screen.queryByTestId('region-overlay')).toBeNull()
  })

  it('a mask that cannot be found falls back to an outline of the part', async () => {
    vi.mocked(getRegion).mockRejectedValueOnce(new Error('REGION_EMPTY'))
    const qc = client([], [makeItem({ id: 'src', board_id: 'b1' })])
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    act(() => selection.select(['src']))
    fireEvent.mouseEnter(screen.getByRole('group', { name: 'Hands' }))
    await waitFor(() => expect(screen.getByTestId('region-overlay').dataset.state).toBe('bbox'))
  })

  it("a selected note's callouts mount once, beside its note bar", () => {
    // the note bar and the callouts were both keyed by the note's id: React kept stray copies
    const note = makeItem({ id: 'n1', board_id: 'b1', kind: 'note', origin: 'note', note_text: 'Olive canvas strap' })
    const qc = client([], [note])
    qc.setQueryData(keys.analysis('n1'), {
      content_type: 'text',
      parse_status: 'completed',
      parts: [{ key: 'opening', label: 'Opening', region_kind: 'text_range', region: [0, 5], mask_url: null, source: 'ai' }],
      dimensions: [],
    })
    renderBoard(qc)
    act(() => selection.select(['n1']))
    expect(screen.getByRole('toolbar', { name: 'Note actions' })).toBeTruthy()
    act(() => selection.clear())
    act(() => selection.select(['n1']))
    expect(document.querySelectorAll('.callout-layer')).toHaveLength(1)
    expect(screen.getAllByRole('group', { name: 'Opening' })).toHaveLength(1)
  })

  it('a note waiting for analysis shows no callouts', () => {
    const note = makeItem({ id: 'n1', board_id: 'b1', kind: 'note', origin: 'note', note_text: 'Olive', parse_status: 'pending' })
    const qc = client([], [note])
    qc.setQueryData(keys.analysis('n1'), { ...analysis, parse_status: 'pending', parts: [], dimensions: [] })
    renderBoard(qc)
    act(() => selection.select(['n1']))
    expect(screen.queryByRole('group', { name: 'Whole item' })).toBeNull()
    expect(document.querySelectorAll('.callout')).toHaveLength(0)
    expect(screen.queryAllByRole('group').filter((g) => g.closest('.callout-layer'))).toHaveLength(0)
  })
})
