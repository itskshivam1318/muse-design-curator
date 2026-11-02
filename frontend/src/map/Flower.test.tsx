import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AnalysisView, type Exploration, type ExploreOption, type Item, keys } from '../api'
import { LENS } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { isCollapsed } from './collapse'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  getRenderers: vi.fn(() => Promise.resolve([])),
  getAnalysis: vi.fn(() => new Promise(() => {})),
  listItems: vi.fn(() => new Promise(() => {})),
}))
const { FlowerLayer } = await import('./Flower')

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`, description: '',
    distance: 'near', value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null,
    ...over,
  }
}

const analysis = (label: string): AnalysisView => ({
  content_type: 'image',
  parse_status: 'completed',
  parts: [{ key: 'hands', label: 'Hands', region_kind: 'box', region: [0.8, 0.4, 0.9, 0.6], mask_url: null, source: 'ai' }],
  dimensions: [
    { key: 'hand_style', label, type: 'physical', part: 'hands', prompt: null, kind: 'enum', value: 'syringe', confidence: 0.9, source: 'ai', status: 'extracted' },
  ],
})

const a = makeItem({ id: 'a', board_id: 'b1', x: 0, y: 0, w: 200, h: 150 })
const b = makeItem({ id: 'b', board_id: 'b1', x: 0, y: 1200, w: 200, h: 150 })
const view = { x: 0, y: 0, scale: 1 }

function setup(explorations: Exploration[], extra: { items?: Item[]; size?: { width: number; height: number } } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.demo, { demo_mode: false, explore_enabled: true })
  qc.setQueryData(keys.explorations('b1'), explorations)
  qc.setQueryData(keys.items('b1'), [a, b, ...(extra.items ?? [])])
  qc.setQueryData(keys.lens('b1'), { spec: LENS })
  qc.setQueryData(keys.analysis('a'), analysis('Hand style'))
  qc.setQueryData(keys.analysis('b'), analysis('Hand shape'))
  render(
    <QueryClientProvider client={qc}>
      <FlowerLayer boardId="b1" items={[a, b]} view={view} size={extra.size ?? { width: 4000, height: 4000 }} />
    </QueryClientProvider>,
  )
  return qc
}

const hub = (label: string) => screen.getByRole('group', { name: `${label} flower` })

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('FlowerLayer', () => {
  it('two flowers open at once both render', () => {
    setup([
      { id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' }), opt({ id: 'o2' }), opt({ id: 'o3', status: 'dismissed' })] },
      { id: 'e2', board_id: 'b1', item_id: 'b', key: 'hand_style', options: [opt({ id: 'o4', exploration_id: 'e2' })] },
    ])
    expect(within(hub('Hand style')).getByText('Hand style')).toBeTruthy()
    expect(within(hub('Hand style')).getByText('2 options · 0 kept')).toBeTruthy()
    expect(within(hub('Hand style')).getAllByTestId('petal').map((p) => p.dataset.optionId)).toEqual(['o1', 'o2'])
    expect(within(hub('Hand shape')).getByText('1 options · 0 kept')).toBeTruthy()
    // a dashed line from the callout to each hub
    expect(document.querySelectorAll('.flower-stem')).toHaveLength(2)
  })

  it('petals show their state: note, rendering, rendered, kept and drifted', () => {
    const shot = (id: string, drifted: string[] = []) =>
      makeItem({ id, board_id: 'b1', origin: 'generated', staged: true, explore_option_id: 'x', check: { target: { answer: 'yes', confidence: 1, note: '' }, kept: 1, of: 1, drifted } })
    setup(
      [
        {
          id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style',
          options: [
            opt({ id: 'o1', distance: 'bold' }),
            opt({ id: 'o2', status: 'visualizing' }),
            opt({ id: 'o3', status: 'visualized', takes: ['t3'] }),
            opt({ id: 'o4', status: 'kept', kept_item_id: 't4', takes: ['t4'] }),
            opt({ id: 'o5', status: 'visualized', takes: ['t5'] }),
          ],
        },
      ],
      { items: [shot('t3'), { ...shot('t4'), staged: false }, shot('t5', ['case_finish'])] },
    )
    const petal = (id: string) => document.querySelector<HTMLElement>(`[data-option-id="${id}"]`)!
    expect(petal('o1').className).toContain('is-note')
    expect(petal('o1').textContent).toContain('Option o1')
    expect(petal('o1').textContent).toContain('bold')
    expect(petal('o2').querySelector('.spinner')).toBeTruthy()
    expect(petal('o3').className).toContain('is-rendered')
    expect(petal('o3').querySelector('img')).toBeTruthy()
    expect(petal('o4').className).toContain('is-kept')
    expect(petal('o4').style.width).toBe('104px')
    expect(petal('o5').className).toContain('is-drifted')
    expect(within(hub('Hand style')).getByText('5 options · 1 kept')).toBeTruthy()
  })

  it('a petal opens its card; Escape closes it', async () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
    fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
    const card = screen.getByRole('dialog', { name: 'Copper' })
    expect(within(card).getByTestId('petal-scope').textContent).toBe('Changes Hands · keeps 0 ✓')
    expect(await within(card).findByRole('button', { name: /Connect a renderer/ })).toBeTruthy()
    fireEvent.keyDown(card, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('collapses to a badge on its callout and opens again; the flag is kept per board', () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' }), opt({ id: 'o2', status: 'kept', kept_item_id: 'k' })] }])
    fireEvent.click(within(hub('Hand style')).getByRole('button', { name: 'Collapse Hand style' }))
    expect(screen.queryByTestId('petal')).toBeNull()
    expect(isCollapsed('b1', 'e1')).toBe(true)
    const badge = screen.getByRole('button', { name: 'Hand style · 2 options · 1 kept' })
    fireEvent.click(badge)
    expect(screen.getAllByTestId('petal')).toHaveLength(2)
    expect(isCollapsed('b1', 'e1')).toBe(false)
  })

  it('only flowers reaching the viewport mount', () => {
    setup(
      [
        { id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' })] },
        { id: 'e2', board_id: 'b1', item_id: 'b', key: 'hand_style', options: [opt({ id: 'o4', exploration_id: 'e2' })] },
      ],
      { size: { width: 800, height: 600 } },
    )
    expect(hub('Hand style')).toBeTruthy()
    expect(screen.queryByRole('group', { name: 'Hand shape flower' })).toBeNull()
  })
})
