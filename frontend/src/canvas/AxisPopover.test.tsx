import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type Exploration, type ExploreOption, type Item, keys } from '../api'
import { LENS } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { axisRows, keptSlot } from './axis'
import { itemBounds } from './nodeProps'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  visualizeOption: vi.fn(),
  keepTake: vi.fn(),
  unkeepTake: vi.fn(),
  patchOption: vi.fn(),
  exploreItem: vi.fn(),
}))
const { visualizeOption, keepTake, unkeepTake, patchOption, exploreItem } = await import('../api')
const { AxisPopover } = await import('./AxisPopover')

function opt(over: Partial<ExploreOption> = {}): ExploreOption {
  return {
    id: 'o1', exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: 'Honey',
    description: 'golden, like old paper', distance: 'near', value: 'honey', keeps: ['case_finish', 'legibility'],
    status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null, ...over,
  }
}

const source = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0, w: 200, h: 150 })
const take = (id: string, over: Partial<Item> = {}) =>
  makeItem({ id, board_id: 'b1', origin: 'generated', staged: true, explore_option_id: 'o1', parent_item_id: 'src', ...over })

function setup(option: ExploreOption, extra: { siblings?: ExploreOption[]; items?: Item[]; locked?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const exploration: Exploration = {
    id: 'e1', board_id: 'b1', item_id: 'src', key: 'dial_color', created_at: '2026-10-28T00:00:01Z',
    options: [opt({ id: 'o0', name: 'Sand' }), option, ...(extra.siblings ?? [])],
  }
  qc.setQueryData(keys.explorations('b1'), [exploration])
  qc.setQueryData(keys.items('b1'), [source, ...(extra.items ?? [])])
  qc.setQueryData(keys.lens('b1'), { spec: LENS })
  const onClose = vi.fn()
  const onOpenOption = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <AxisPopover option={option} exploration={exploration} source={source} onClose={onClose} onOpenOption={onOpenOption} locked={extra.locked} />
    </QueryClientProvider>,
  )
  const current = () => qc.getQueryData<Exploration[]>(keys.explorations('b1'))![0].options.find((o) => o.id === option.id)!
  return { qc, exploration, onClose, onOpenOption, current }
}

beforeEach(() => {
  for (const f of [visualizeOption, keepTake, unkeepTake, patchOption, exploreItem]) vi.mocked(f).mockReset()
})
afterEach(cleanup)

describe('AxisPopover', () => {
  it('not visualized: name and description, what it keeps, and Visualize calls visualizeOption', async () => {
    vi.mocked(visualizeOption).mockResolvedValue(undefined)
    const { current } = setup(opt())
    expect(screen.getByText('Honey').tagName).toBe('B')
    expect(screen.getByText(/golden, like old paper/)).toBeTruthy()
    expect(screen.getByText('Keeps Case finish, Legibility. Only Dial colour changes.')).toBeTruthy()
    for (const name of ['Branch', 'Find real examples', 'Dismiss']) expect(screen.getByRole('button', { name })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Visualize' }))
    await waitFor(() => expect(visualizeOption).toHaveBeenCalledWith('o1'))
    expect(current().status).toBe('visualizing') // shown at once
  })

  it('visualizing with no take yet shows progress', () => {
    setup(opt({ status: 'visualizing' }))
    expect(screen.getByRole('status').textContent).toMatch(/Visualizing Honey/)
    expect(screen.queryByRole('button', { name: 'Visualize' })).toBeNull()
  })

  it('with 2 takes the pager shows take 2, pages back to take 1, and Keep sends the kept slot', async () => {
    const t1 = take('t1')
    const t2 = take('t2', { check: { target: { answer: 'yes', confidence: 1, note: '' }, kept: 2, of: 2 } })
    const option = opt({ status: 'visualized', takes: ['t1', 't2'] })
    vi.mocked(keepTake).mockResolvedValue({ ...option, status: 'kept', kept_item_id: 't2' })
    const { exploration, onClose, current, qc } = setup(option, { items: [t1, t2] })
    expect(screen.getByText('Honey · take 2')).toBeTruthy()
    expect(screen.getByText('Dial colour → Honey ✓ · 2 of 2 kept')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Honey · take 2' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Previous take' }))
    expect(screen.getByText('Honey · take 1')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next take' }))
    expect((screen.getByRole('button', { name: 'Next take' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    const row = axisRows(itemBounds(source), [exploration], new Map())[0]
    await waitFor(() => expect(keepTake).toHaveBeenCalledWith('o1', 't2', keptSlot(row, 'o1')))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(current().kept_item_id).toBe('t2')
    const kept = qc.getQueryData<Item[]>(keys.items('b1'))!.find((i) => i.id === 't2')!
    expect(kept).toMatchObject({ staged: false, ...keptSlot(row, 'o1') })
  })

  it('a kept option opens on its kept take with Un-keep, which calls unkeepTake', async () => {
    const t1 = take('t1', { staged: false })
    const t2 = take('t2')
    const option = opt({ status: 'kept', takes: ['t1', 't2'], kept_item_id: 't1' })
    vi.mocked(unkeepTake).mockResolvedValue({ ...option, status: 'visualized', kept_item_id: null })
    const { current } = setup(option, { items: [t1, t2] })
    expect(screen.getByText('Honey · take 1')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Un-keep' }))
    await waitFor(() => expect(unkeepTake).toHaveBeenCalledWith('o1'))
    await waitFor(() => expect(current().kept_item_id).toBeNull())
  })

  it('Regenerate calls visualizeOption again', async () => {
    vi.mocked(visualizeOption).mockResolvedValue(undefined)
    setup(opt({ status: 'visualized', takes: ['t1'] }), { items: [take('t1')] })
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    await waitFor(() => expect(visualizeOption).toHaveBeenCalledWith('o1'))
  })

  it('branches are listed inside the popover; Branch asks for more under this option', async () => {
    const e = { id: 'e1', board_id: 'b1', item_id: 'src', key: 'dial_color', options: [] }
    vi.mocked(exploreItem).mockResolvedValue(e)
    const { onOpenOption } = setup(opt(), { siblings: [opt({ id: 'o1a', name: 'Dark honey', parent_option_id: 'o1' })] })
    fireEvent.click(screen.getByRole('button', { name: /Dark honey/ }))
    expect(onOpenOption).toHaveBeenCalledWith('o1a')
    fireEvent.click(screen.getByRole('button', { name: 'Branch' }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('src', { key: 'dial_color', parent_option_id: 'o1' }))
  })

  it('Dismiss patches the option and closes', async () => {
    vi.mocked(patchOption).mockResolvedValue(opt({ status: 'dismissed' }))
    const { onClose } = setup(opt())
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(patchOption).toHaveBeenCalledWith('o1', { status: 'dismissed' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('locked: actions are disabled', () => {
    setup(opt(), { locked: true })
    expect((screen.getByRole('button', { name: 'Visualize' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Dismiss' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
