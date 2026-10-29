import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type Exploration, type ExploreOption, itemImageUrl, keys } from '../api'
import { hoverStore, setHoveredOption } from '../explore/hover'
import { LENS } from '../test/attrs'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), exploreItem: vi.fn() }))
const { exploreItem } = await import('../api')
const { AxisLayer } = await import('./AxisLayer')
const { focusAxis } = await import('./axis')

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: over.id, description: '',
    distance: 'near', value: over.id, keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [],
    x: null, y: null, ...over,
  }
}

const source = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0, w: 200, h: 150 })
const kept = makeItem({ id: 'k1', board_id: 'b1', origin: 'generated', explore_option_id: 'o2', parent_item_id: 'src' })

function exploration(id: string, options: ExploreOption[], created_at = '2026-10-28T00:00:01Z'): Exploration {
  return { id, board_id: 'b1', item_id: 'src', key: id === 'e1' ? 'dial_color' : 'case_finish', created_at, options }
}

function setup(list: Exploration[], selectedId: string | null = 'src', locked = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.explorations('b1'), list)
  qc.setQueryData(keys.items('b1'), [source, kept])
  qc.setQueryData(keys.lens('b1'), { spec: LENS })
  const utils = render(
    <QueryClientProvider client={qc}>
      <AxisLayer
        items={[source, kept]}
        explorations={list}
        selectedId={selectedId}
        view={{ x: 0, y: 0, scale: 1 }}
        locked={locked}
      />
    </QueryClientProvider>,
  )
  return { qc, ...utils }
}

const e1 = () =>
  exploration('e1', [
    opt({ id: 'o1', name: 'Sand', description: 'pale, low saturation', distance: 'bold' }),
    opt({ id: 'o2', name: 'Honey', description: 'golden', status: 'kept', kept_item_id: 'k1', takes: ['k1'] }),
    opt({ id: 'o3', name: 'Gone', status: 'dismissed' }),
  ])

beforeEach(() => vi.mocked(exploreItem).mockReset())
afterEach(() => {
  cleanup()
  setHoveredOption(null)
  focusAxis(null)
})

describe('AxisLayer', () => {
  it('draws text cards with name, description and a distance dot, and the label above the line', () => {
    setup([e1()])
    const card = screen.getByRole('button', { name: /Sand/ })
    expect(card.textContent).toContain('pale, low saturation')
    expect(card.querySelector('.axis-dot')?.getAttribute('data-distance')).toBe('bold')
    expect(screen.getByText('Dial colour')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Gone/ })).toBeNull()
  })

  it('a kept option renders the kept item thumbnail labelled "Honey · kept"', () => {
    setup([e1()])
    const card = screen.getByRole('button', { name: 'Honey · kept' })
    const img = card.querySelector('img')!
    expect(img.getAttribute('src')).toBe(itemImageUrl(kept, 'thumb'))
    expect(card.querySelector('.axis-kept-tag')?.textContent).toBe('· kept')
  })

  it('the line is accent for the selected source and grey otherwise', () => {
    const { unmount } = setup([e1()], 'src')
    expect(document.querySelector('.axis-line')?.getAttribute('data-active')).toBe('true')
    unmount()
    setup([e1()], null)
    expect(document.querySelector('.axis-line')?.getAttribute('data-active')).toBe('false')
  })

  it('a focused axis is the only accent row of its source', () => {
    focusAxis('e2')
    setup([e1(), exploration('e2', [opt({ id: 'p1', exploration_id: 'e2' })], '2026-10-28T00:00:02Z')])
    const lines = [...document.querySelectorAll('.axis-line')].map((l) => l.getAttribute('data-active'))
    expect(lines).toEqual(['false', 'true'])
  })

  it('hovering a card highlights it in the drawer too (shared hover store), and a hovered option lights its card', () => {
    setup([e1()])
    const card = screen.getByRole('button', { name: /Sand/ })
    fireEvent.mouseEnter(card)
    expect(hoverStore.get()).toBe('o1')
    expect(card.className).toContain('is-hovered')
    fireEvent.mouseLeave(card)
    expect(hoverStore.get()).toBeNull()
  })

  it('clicking a card opens its popover; clicking it again closes it', () => {
    setup([e1()])
    fireEvent.click(screen.getByRole('button', { name: /Sand/ }))
    const dialog = screen.getByRole('dialog', { name: 'Sand' })
    expect(dialog.textContent).toContain('Visualize')
    expect(screen.getByRole('button', { name: /Sand/, pressed: true })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Sand/ }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('the end handle opens More / Further / steer', async () => {
    vi.mocked(exploreItem).mockResolvedValue(e1())
    setup([e1()])
    fireEvent.click(screen.getByRole('button', { name: 'More Dial colour options' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Steer Dial colour' }), { target: { value: 'warmer' } })
    fireEvent.click(screen.getByRole('button', { name: 'Further' }))
    await waitFor(() =>
      expect(exploreItem).toHaveBeenCalledWith('src', { key: 'dial_color', mode: 'further', steer: 'warmer' }),
    )
  })
})
