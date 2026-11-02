import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import Konva from 'konva'
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
  getRenderers: vi.fn(() => Promise.resolve([])),
}))
const { getRegion, exploreItem, visualizeOption } = await import('../api')
const { setCollapsed } = await import('../map/collapse')
const { useItemActions } = await import('./actions')
const { Canvas } = await import('./Canvas')
const { undoHistory } = await import('./history')

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`,
    description: '', distance: 'near', value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null,
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

/** The board page in small: the canvas over the cached items, with the real item actions. */
function Board({ onOpenPanel = vi.fn() }: { onOpenPanel?: (...args: unknown[]) => void }) {
  const items = useQuery<Item[]>({ queryKey: keys.items('b1'), queryFn: () => [] }).data ?? []
  const actions = useItemActions('b1')
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
    const e: Exploration = { id: 'e1', board_id: 'b1', item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' }), opt({ id: 'o2', name: 'Ember' })] }
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
      [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
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

  it('draws no flowers when explore is off', () => {
    sized()
    const qc = client(
      [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1' })] }],
      [makeItem({ id: 'src', board_id: 'b1' })],
      false,
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    expect(screen.queryAllByTestId('petal')).toEqual([])
  })

  it('kept result is an ordinary item on the board, not hidden', () => {
    sized()
    const src = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })
    const kept = makeItem({ id: 'k1', board_id: 'b1', x: 700, y: 0, original_filename: 'Honey.png', explore_option_id: 'o1', origin: 'generated', parent_item_id: 'src' })
    const qc = client(
      [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', name: 'Honey', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
      [src, kept],
    )
    qc.setQueryData(keys.analysis('src'), analysis)
    renderBoard(qc)
    // drawn on the stage where it was placed, and listed like any item
    const node = Konva.stages.at(-1)!.findOne('#k1')!
    expect(node.visible()).toBe(true)
    expect(node.x()).toBe(700)
    expect(screen.getByRole('list', { name: 'Items on this board' }).textContent).toContain('Honey.png')
    // its petal shows it kept
    expect(document.querySelector('[data-option-id="o1"]')!.className).toContain('is-kept')
  })

  it('a kept result gets its own callouts when selected', () => {
    sized()
    const src = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })
    const kept = makeItem({ id: 'k1', board_id: 'b1', x: 700, y: 0, explore_option_id: 'o1', origin: 'generated', parent_item_id: 'src' })
    const qc = client(
      [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'hand_style', options: [opt({ id: 'o1', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
      [src, kept],
    )
    qc.setQueryData(keys.analysis('k1'), analysis)
    renderBoard(qc)
    act(() => selection.select(['k1']))
    expect(screen.getByRole('group', { name: 'Hands' })).toBeTruthy()
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
