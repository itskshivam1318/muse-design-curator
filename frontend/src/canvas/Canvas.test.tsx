import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, cleanup, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import Konva from 'konva'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type Exploration, type ExploreOption, type Item, keys } from '../api'
import { stubCanvasContext } from '../test/canvasStub'
import { makeItem } from '../test/fixtures'
import type { ItemActions } from './actions'
import { selection } from './selection'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), patchItem: vi.fn(() => Promise.resolve()) }))
const { patchItem } = await import('../api')
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

let boardActions: ItemActions | null = null

/** The board page in small: the canvas over the cached items, with the real item actions. */
function Board() {
  const items = useQuery<Item[]>({ queryKey: keys.items('b1'), queryFn: () => [] }).data ?? []
  const actions = useItemActions('b1')
  useEffect(() => {
    boardActions = actions
  })
  return <Canvas boardId="b1" items={items} actions={actions} onFiles={vi.fn()} onOpenPanel={vi.fn()} spaceDown={false} />
}

function renderBoard(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <Board />
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
  boardActions = null
})

describe('Canvas axes', () => {
  it('lists one axis card per non-dismissed option of a visible source', () => {
    renderBoard(
      client(
        [
          { id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options: [opt({ id: 'o1' }), opt({ id: 'o2', status: 'dismissed' }), opt({ id: 'o3' })] },
          { id: 'e2', board_id: 'b1', item_id: 'removed', key: 'case_finish', options: [opt({ id: 'o4', exploration_id: 'e2' })] },
        ],
        [makeItem({ id: 'src', board_id: 'b1' })],
      ),
    )
    const cards = screen.getAllByTestId('axis-card')
    expect(cards.map((n) => n.getAttribute('data-option-id'))).toEqual(['o1', 'o3'])
  })

  it('draws no axes when explore is off', () => {
    renderBoard(
      client(
        [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options: [opt({ id: 'o1' })] }],
        [makeItem({ id: 'src', board_id: 'b1' })],
        false,
      ),
    )
    expect(screen.queryAllByTestId('axis-card')).toEqual([])
  })

  it('a kept take is drawn as its axis card, not as a loose item', () => {
    const src = makeItem({ id: 'src', board_id: 'b1' })
    const kept = makeItem({ id: 'k1', board_id: 'b1', original_filename: 'Honey.png', explore_option_id: 'o1', origin: 'generated' })
    renderBoard(
      client(
        [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options: [opt({ id: 'o1', name: 'Honey', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
        [src, kept],
      ),
    )
    expect(screen.getByRole('button', { name: 'Honey · kept' })).toBeTruthy()
    expect(screen.getByRole('list', { name: 'Items on this board' }).textContent).not.toContain('Honey.png')
  })

  it('moving a source moves its kept items in the same undo entry; undo puts both back', () => {
    stubCanvasContext()
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1000)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(800)
    const src = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0 })
    const kept = makeItem({ id: 'k1', board_id: 'b1', x: 240, y: 28, explore_option_id: 'o1', origin: 'generated' })
    const other = makeItem({ id: 'far', board_id: 'b1', x: 900, y: 900 })
    const qc = client(
      [{ id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options: [opt({ id: 'o1', status: 'kept', kept_item_id: 'k1', takes: ['k1'] })] }],
      [src, kept, other],
    )
    renderBoard(qc)
    const node = Konva.stages.at(-1)!.findOne('#src')!
    act(() => {
      node.fire('dragstart', { evt: new MouseEvent('dragstart') })
      node.position({ x: 30, y: 40 })
      node.fire('dragmove', { evt: new MouseEvent('dragmove') })
      node.fire('dragend', { evt: new MouseEvent('dragend') })
    })
    const pos = () => Object.fromEntries(qc.getQueryData<Item[]>(keys.items('b1'))!.map((i) => [i.id, [i.x, i.y]]))
    expect(pos()).toEqual({ src: [30, 40], k1: [270, 68], far: [900, 900] })
    expect(patchItem).toHaveBeenCalledWith('k1', { x: 270, y: 68 })
    expect(undoHistory.size).toBe(1)
    act(() => {
      boardActions!.undo()
    })
    expect(pos()).toEqual({ src: [0, 0], k1: [240, 28], far: [900, 900] })
    expect(undoHistory.size).toBe(0)
  })
})
