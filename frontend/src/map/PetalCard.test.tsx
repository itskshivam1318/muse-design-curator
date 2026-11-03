import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type Exploration, type ExploreOption, type Item, keys, type RendererInfo } from '../api'
import { selection } from '../canvas/selection'
import { railStore, closeRail } from '../shell/tools'
import { LENS } from '../test/attrs'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  visualizeOption: vi.fn(),
  keepTake: vi.fn(),
  patchOption: vi.fn(),
  exploreItem: vi.fn(),
  getRenderers: vi.fn(),
  listItems: vi.fn(() => new Promise(() => {})),
}))
const { visualizeOption, keepTake, patchOption, exploreItem, getRenderers } = await import('../api')
const { PetalCard } = await import('./PetalCard')
const { createLivingWorld } = await import('../living/world')
const { LivingProvider } = await import('../living/useLiving')

const MUSE_IMAGE: RendererInfo = { id: 'muse-image', title: 'Generate image', detail: 'Muse Image · inside the Hands mask', builtin: true }

function opt(over: Partial<ExploreOption> = {}): ExploreOption {
  return {
    id: 'o1', exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: 'Copper dauphine',
    description: 'Polished copper dauphine hands', distance: 'bold', value: 'copper_dauphine',
    keeps: ['case_finish', 'legibility', 'date_window'], status: 'open', last_error: null, kept_item_id: null,
    takes: [], x: null, y: null, undocked: false, ...over,
  }
}

const source = makeItem({ id: 'src', board_id: 'b1', x: 0, y: 0, w: 200, h: 150 })
const take = (id: string, over: Partial<Item> = {}) =>
  makeItem({ id, board_id: 'b1', origin: 'generated', staged: true, explore_option_id: 'o1', parent_item_id: 'src', w: 200, h: 150, ...over })

function setup(option: ExploreOption, extra: { items?: Item[]; renderers?: RendererInfo[]; keepAt?: (t: Item) => { at?: { x: number; y: number }; size: { w: number; h: number } } } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const exploration: Exploration = { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [option] }
  qc.setQueryData(keys.explorations('b1'), [exploration])
  qc.setQueryData(keys.items('b1'), [source, ...(extra.items ?? [])])
  qc.setQueryData(keys.lens('b1'), { spec: LENS })
  vi.mocked(getRenderers).mockResolvedValue(extra.renderers ?? [MUSE_IMAGE])
  const onClose = vi.fn()
  const world = createLivingWorld({ reduced: true })
  render(
    <QueryClientProvider client={qc}>
      <LivingProvider world={world}>
        <PetalCard
          option={option}
          dimension={{ key: 'hand_style', label: 'Hand style', part: 'Hands' }}
          item={source}
          keepAt={extra.keepAt ?? (() => ({ at: { x: 500, y: 40 }, size: { w: 168, h: 126 } }))}
          onClose={onClose}
        />
      </LivingProvider>
    </QueryClientProvider>,
  )
  const current = () => qc.getQueryData<Exploration[]>(keys.explorations('b1'))![0].options[0]
  return { qc, onClose, current, world }
}

beforeEach(() => {
  for (const f of [visualizeOption, keepTake, patchOption, exploreItem, getRenderers]) vi.mocked(f).mockReset()
})
afterEach(() => {
  cleanup()
  selection.clear()
  closeRail()
})

describe('PetalCard', () => {
  it('petal card button names the renderer: "Generate image" / "Muse Image · inside the Hands mask"', async () => {
    vi.mocked(visualizeOption).mockResolvedValue(undefined)
    const { current } = setup(opt())
    expect(screen.getByText('Copper dauphine')).toBeTruthy()
    expect(screen.getByText('bold')).toBeTruthy()
    expect(screen.getByText('Polished copper dauphine hands')).toBeTruthy()
    expect(screen.getByTestId('petal-scope').textContent).toBe('Changes Hands · keeps 3 ✓')
    const button = await screen.findByRole('button', { name: /^Generate image/ })
    expect(button.textContent).toContain('Muse Image · inside the Hands mask')
    expect(getRenderers).toHaveBeenCalledWith('src', 'hand_style')
    fireEvent.click(button)
    await waitFor(() => expect(visualizeOption).toHaveBeenCalledWith('o1', { renderer_id: 'muse-image' }))
    expect(current().status).toBe('visualizing') // spins at once
  })

  it('after a render (start and result) the card holds focus again, so Escape still closes it', async () => {
    vi.mocked(visualizeOption).mockResolvedValue(undefined)
    const { qc, onClose } = setup(opt())
    const button = await screen.findByRole('button', { name: /^Generate image/ })
    button.focus()
    fireEvent.click(button)
    await screen.findByRole('status') // rendering: the button that had focus is gone
    const card = screen.getByRole('dialog', { name: 'Copper dauphine' })
    await waitFor(() => expect(document.activeElement).toBe(card))
    // the result lands (the server's explore.updated and item.added)
    const t = take('t1', { check: { target: { answer: 'yes', confidence: 0.9, note: '' }, kept: 3, of: 3, drifted: [] } })
    act(() => {
      qc.setQueryData(keys.items('b1'), [source, t])
      qc.setQueryData(keys.explorations('b1'), [
        { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [opt({ status: 'visualized', takes: ['t1'] })] },
      ])
    })
    await screen.findByRole('button', { name: 'Keep' })
    expect(document.activeElement).toBe(card)
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('no renderer → "Connect a renderer"', async () => {
    setup(opt(), { renderers: [] })
    const connect = await screen.findByRole('button', { name: /Connect a renderer/ })
    expect(screen.queryByRole('button', { name: /Generate image/ })).toBeNull()
    fireEvent.click(connect)
    expect(railStore.get().open).toBe('plugins')
    expect(visualizeOption).not.toHaveBeenCalled()
  })

  it('renderers that fail to load show an error with Retry, not "Connect a renderer"', async () => {
    const { qc } = setup(opt(), { renderers: [] })
    await screen.findByRole('button', { name: /Connect a renderer/ })
    vi.mocked(getRenderers).mockRejectedValueOnce(new ApiError(500, 'BOOM', 'Server error'))
    await act(() => qc.resetQueries({ queryKey: keys.renderers('src', 'hand_style') }))
    expect((await screen.findByRole('alert')).textContent).toBe('Server error')
    expect(screen.queryByRole('button', { name: /Connect a renderer/ })).toBeNull()
    vi.mocked(getRenderers).mockResolvedValueOnce([MUSE_IMAGE])
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('button', { name: /^Generate image/ })).toBeTruthy()
  })

  it('a passed result shows its check line, Keep and Not this; Keep docks it in its slot at the docked size', async () => {
    const t = take('t1', { check: { target: { answer: 'yes', confidence: 0.9, note: '' }, kept: 3, of: 3, drifted: [] } })
    const kept = opt({ status: 'kept', kept_item_id: 't1', takes: ['t1'] })
    vi.mocked(keepTake).mockResolvedValue(kept)
    const keepAt = vi.fn(() => ({ at: { x: 500, y: 40 }, size: { w: 168, h: 126 } }))
    const { qc, onClose, current, world } = setup(opt({ status: 'visualized', takes: ['t1'] }), { items: [t], keepAt })
    const pulse = vi.spyOn(world, 'pulse')
    expect(screen.getByText('✓ Reads as Copper dauphine · 3 of 3 kept').className).toContain('is-ok')
    expect(screen.getByRole('button', { name: 'Not this' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(keepTake).toHaveBeenCalledWith('o1', 't1', { x: 500, y: 40 }, { w: 168, h: 126 }))
    expect(keepAt).toHaveBeenCalledWith(t)
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(current().status).toBe('kept')
    // un-staged where it was placed, at the docked size: an ordinary board item now, swelling as it lands
    expect(qc.getQueryData<Item[]>(keys.items('b1'))!.find((i) => i.id === 't1')).toMatchObject({ staged: false, x: 500, y: 40, w: 168, h: 126 })
    expect(pulse).toHaveBeenCalledWith('t1')
  })

  it('drifted result shows Retry and no Keep', async () => {
    const t = take('t1', { check: { target: { answer: 'yes', confidence: 0.9, note: '' }, kept: 2, of: 3, drifted: ['case_finish'] } })
    vi.mocked(visualizeOption).mockResolvedValue(undefined)
    vi.mocked(patchOption).mockResolvedValue(opt({ status: 'dismissed', takes: ['t1'] }))
    setup(opt({ status: 'visualized', takes: ['t1'] }), { items: [t] })
    expect(screen.getByText('✕ Case finish drifted. Not added.').className).toContain('is-drift')
    expect(screen.queryByRole('button', { name: 'Keep' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Drop' }))
    await waitFor(() => expect(patchOption).toHaveBeenCalledWith('o1', { status: 'dismissed' }))
    const retry = screen.getByRole('button', { name: 'Retry' }) as HTMLButtonElement
    await waitFor(() => expect(retry.disabled).toBe(false)) // once the renderer is known
    fireEvent.click(retry)
    await waitFor(() => expect(visualizeOption).toHaveBeenCalledWith('o1', { renderer_id: 'muse-image' }))
  })

  it('a daily limit shows its message inline', async () => {
    const message = 'Daily limit reached for this board, try tomorrow.'
    vi.mocked(visualizeOption).mockRejectedValue(new ApiError(429, 'DAILY_LIMIT', message))
    const { current } = setup(opt())
    fireEvent.click(await screen.findByRole('button', { name: /^Generate image/ }))
    expect((await screen.findByRole('alert')).textContent).toBe(message)
    expect(current().status).toBe('open') // put back
  })

  it('More like this explores more from this option; Dismiss dismisses; there is no Branch', async () => {
    const keptOpt = opt({ status: 'kept', kept_item_id: 'k1', takes: ['k1'] })
    const e: Exploration = { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'src', key: 'hand_style', options: [keptOpt, opt({ id: 'o2', parent_option_id: 'o1' })] }
    vi.mocked(exploreItem).mockResolvedValue(e)
    vi.mocked(patchOption).mockResolvedValue(opt({ status: 'dismissed' }))
    const k = take('k1', { staged: false })
    setup(keptOpt, { items: [k] })
    expect(screen.getByText('✓ kept · on the board')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'More like this' }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('src', { key: 'hand_style', mode: 'more', parent_option_id: 'o1' }))
    expect(screen.queryByRole('button', { name: 'Branch' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(patchOption).toHaveBeenCalledWith('o1', { status: 'dismissed' }))
  })
})
