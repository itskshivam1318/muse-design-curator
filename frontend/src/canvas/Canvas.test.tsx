import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type Exploration, type ExploreOption, keys } from '../api'
import { makeItem } from '../test/fixtures'
import type { ItemActions } from './actions'
import { Canvas } from './Canvas'

afterEach(cleanup)

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`,
    description: '', distance: 'near', value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null,
    ...over,
  }
}

describe('Canvas notes', () => {
  it('lists one option-note per visible note, and a note opens the explore panel on its option', () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    qc.setQueryData(keys.demo, { demo_mode: false })
    const explorations: Exploration[] = [
      { id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options: [opt({ id: 'o1' }), opt({ id: 'o2', status: 'dismissed' }), opt({ id: 'o3' })] },
      { id: 'e2', board_id: 'b1', item_id: 'removed', key: 'case_finish', options: [opt({ id: 'o4', exploration_id: 'e2' })] },
    ]
    qc.setQueryData(keys.explorations('b1'), explorations)
    const onOpenPanel = vi.fn()
    render(
      <QueryClientProvider client={qc}>
        <Canvas
          boardId="b1"
          items={[makeItem({ id: 'src', board_id: 'b1' })]}
          actions={{} as ItemActions}
          onFiles={vi.fn()}
          onOpenPanel={onOpenPanel}
          spaceDown={false}
        />
      </QueryClientProvider>,
    )
    const notes = screen.getAllByTestId('option-note')
    expect(notes.map((n) => n.getAttribute('data-option-id'))).toEqual(['o1', 'o3'])
    fireEvent.click(screen.getByRole('button', { name: /Option o3/ }))
    expect(onOpenPanel).toHaveBeenCalledWith('explore', 'src', { key: 'case_finish', optionId: 'o3' })
    vi.unstubAllGlobals()
  })

  it('draws no notes when explore is off', () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    qc.setQueryData(keys.demo, { demo_mode: false, explore_enabled: false })
    qc.setQueryData(keys.explorations('b1'), [
      { id: 'e1', board_id: 'b1', item_id: 'src', key: 'case_finish', options: [opt({ id: 'o1' })] },
    ])
    render(
      <QueryClientProvider client={qc}>
        <Canvas
          boardId="b1"
          items={[makeItem({ id: 'src', board_id: 'b1' })]}
          actions={{} as ItemActions}
          onFiles={vi.fn()}
          onOpenPanel={vi.fn()}
          spaceDown={false}
        />
      </QueryClientProvider>,
    )
    expect(screen.queryAllByTestId('option-note')).toEqual([])
    vi.unstubAllGlobals()
  })
})
