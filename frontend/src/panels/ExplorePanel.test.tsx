import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, keys, type Exploration, type ExploreOption, type ItemAttributes } from '../api'
import { undoHistory } from '../canvas/history'
import { hoverStore, setHoveredOption } from '../explore/hover'
import { makeAttrs } from '../test/attrs'
import { makeItem, makeProfile } from '../test/fixtures'
import { runStore } from '../vary/runStore'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  exploreItem: vi.fn(),
  patchOption: vi.fn(),
  visualizeOption: vi.fn(),
  createRun: vi.fn(),
}))
const { exploreItem, patchOption, visualizeOption, createRun } = await import('../api')
const { ExplorePanel } = await import('./ExplorePanel')

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`,
    description: `Looks like ${over.id}`, distance: 'near', value: 'brushed', keeps: ['dial_color'],
    status: 'open', last_error: null, x: null, y: null, created_at: '2026-10-28T00:00:00Z', ...over,
  }
}

function exploration(options: ExploreOption[]): Exploration {
  return { id: 'e1', board_id: 'b1', item_id: 'i1', key: 'case_finish', options }
}

beforeEach(() => {
  vi.mocked(exploreItem).mockReset()
  vi.mocked(patchOption).mockReset()
  vi.mocked(visualizeOption).mockReset()
  vi.mocked(createRun).mockReset()
})

afterEach(() => {
  cleanup()
  runStore.clear()
  setHoveredOption(null)
  undoHistory.clear()
})

function setup({ params, explorations = [], locked = false, attrs = makeAttrs() }: {
  params?: Record<string, unknown>
  explorations?: Exploration[]
  locked?: boolean
  attrs?: ItemAttributes
} = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), [makeItem({ id: 'i1', board_id: 'b1', original_filename: 'watch.png' })])
  qc.setQueryData(keys.attributes('i1'), attrs)
  qc.setQueryData(keys.profile('b1'), { version: 1, profile: makeProfile() })
  qc.setQueryData(keys.explorations('b1'), explorations)
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <ExplorePanel boardId="b1" itemId="i1" params={params} onClose={onClose} locked={locked} />
    </QueryClientProvider>,
  )
  return { qc, onClose }
}

describe('ExplorePanel', () => {
  it('explore button calls exploreItem with steer', async () => {
    vi.mocked(exploreItem).mockResolvedValue(exploration([opt({ id: 'o1' })]))
    setup()
    fireEvent.click(screen.getByRole('button', { name: /Case finish/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /steer/i }), { target: { value: 'more industrial' } })
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('i1', { key: 'case_finish', mode: 'initial', steer: 'more industrial' }))
    // the returned exploration lands in the cache: its options show without waiting for the event
    expect(await screen.findByText('Option o1')).toBeTruthy()
  })

  it('more sends mode more', async () => {
    vi.mocked(exploreItem).mockResolvedValue(exploration([opt({ id: 'o1' })]))
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' })])] })
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('i1', { key: 'case_finish', mode: 'more' }))
    fireEvent.click(screen.getByRole('button', { name: 'Further' }))
    await waitFor(() => expect(exploreItem).toHaveBeenLastCalledWith('i1', { key: 'case_finish', mode: 'further' }))
  })

  it('branch sends parent_option_id', async () => {
    vi.mocked(exploreItem).mockResolvedValue(exploration([opt({ id: 'o1' }), opt({ id: 'o2', parent_option_id: 'o1', batch: 2 })]))
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' })])] })
    fireEvent.click(screen.getByRole('button', { name: 'Branch Option o1' }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('i1', { key: 'case_finish', parent_option_id: 'o1' }))
    const child = await screen.findByText('Option o2')
    expect(child.closest('li')?.getAttribute('data-depth')).toBe('1')
  })

  it('branch sends the steer text when there is one', async () => {
    vi.mocked(exploreItem).mockResolvedValue(exploration([opt({ id: 'o1' }), opt({ id: 'o2', parent_option_id: 'o1', batch: 2 })]))
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' })])] })
    fireEvent.change(screen.getByRole('textbox', { name: /steer/i }), { target: { value: 'warmer' } })
    fireEvent.click(screen.getByRole('button', { name: 'Branch Option o1' }))
    await waitFor(() =>
      expect(exploreItem).toHaveBeenCalledWith('i1', { key: 'case_finish', parent_option_id: 'o1', steer: 'warmer' }),
    )
  })

  it('visualize calls visualizeOption and shows spinner from status', async () => {
    vi.mocked(visualizeOption).mockResolvedValue(undefined)
    const { qc } = setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' })])] })
    expect(screen.queryByRole('status', { name: 'Visualizing' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Visualize Option o1' }))
    await waitFor(() => expect(visualizeOption).toHaveBeenCalledWith('o1'))
    expect(await screen.findByRole('status', { name: 'Visualizing' })).toBeTruthy()
    // the server's event ends it with an error: the spinner goes and the row says so
    act(() => qc.setQueryData(keys.explorations('b1'), [exploration([opt({ id: 'o1', last_error: 'GENERATION_FAILED' })])]))
    expect(await screen.findByText("Couldn't visualize, try again.")).toBeTruthy()
    expect(screen.queryByRole('status', { name: 'Visualizing' })).toBeNull()
  })

  it('a refused visualize puts the row back and shows the message', async () => {
    vi.mocked(visualizeOption).mockRejectedValue(new ApiError(403, 'DEMO_LOCKED', 'Unlock the demo to visualize'))
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' })])] })
    fireEvent.click(screen.getByRole('button', { name: 'Visualize Option o1' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Unlock the demo to visualize')
    await waitFor(() => expect(screen.queryByRole('status', { name: 'Visualizing' })).toBeNull())
  })

  it('dismiss patches status', async () => {
    vi.mocked(patchOption).mockResolvedValue(opt({ id: 'o1', status: 'dismissed' }))
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' }), opt({ id: 'o2' })])] })
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss Option o1' }))
    await waitFor(() => expect(patchOption).toHaveBeenCalledWith('o1', { status: 'dismissed' }))
    await waitFor(() => expect(screen.queryByText('Option o1')).toBeNull())
    expect(screen.getByText('Option o2')).toBeTruthy()
    // ⌘Z reopens it: the dismiss is on the board's undo stack
    vi.mocked(patchOption).mockResolvedValue(opt({ id: 'o1' }))
    const entry = undoHistory.pop()
    act(() => {
      if (entry?.kind === 'revert') entry.revert()
    })
    await waitFor(() => expect(patchOption).toHaveBeenLastCalledWith('o1', { status: 'open' }))
    expect(await screen.findByText('Option o1')).toBeTruthy()
  })

  it('error message shown on 502', async () => {
    vi.mocked(exploreItem).mockRejectedValue(new ApiError(502, 'EXPLORE_EMPTY', 'The model returned no usable new options'))
    setup({ params: { key: 'case_finish' } })
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }))
    expect((await screen.findByRole('alert')).textContent).toBe('The model returned no usable new options')
  })

  it('hover sets hovered option', () => {
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' }), opt({ id: 'o2' })])] })
    const row = screen.getByText('Option o1').closest('li')!
    fireEvent.mouseEnter(row)
    expect(hoverStore.get()).toBe('o1')
    expect(row.className).toMatch(/is-hovered/)
    fireEvent.mouseLeave(row)
    expect(hoverStore.get()).toBeNull()
    // hovering the note on the canvas highlights the row here
    act(() => setHoveredOption('o2'))
    expect(screen.getByText('Option o2').closest('li')!.className).toMatch(/is-hovered/)
    expect(row.className).not.toMatch(/is-hovered/)
  })

  it('params.key opens that attribute expanded', () => {
    setup({ params: { key: 'case_finish', optionId: 'o2' }, explorations: [exploration([opt({ id: 'o1' }), opt({ id: 'o2' })])] })
    expect(screen.getByRole('button', { name: /Case finish/ }).getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('button', { name: /Legibility/ }).getAttribute('aria-expanded')).toBe('false')
    expect(screen.getByText('Option o1')).toBeTruthy()
    expect(screen.getByText('Option o2').closest('li')!.className).toMatch(/is-focused/)
  })

  it('find real examples starts a run with the option and keeps the panel open', async () => {
    vi.mocked(createRun).mockResolvedValue({ run_id: 'r1' })
    const { onClose } = setup({
      params: { key: 'case_finish' },
      explorations: [exploration([opt({ id: 'o1', value: 'polished' }), opt({ id: 'o2', value: 'sandblasted' })])],
    })
    const off = screen.getByRole('button', { name: 'Find real examples Option o2' }) as HTMLButtonElement
    expect(off.disabled).toBe(true)
    expect(off.title).toMatch(/Visualize/)
    fireEvent.click(screen.getByRole('button', { name: 'Find real examples Option o1' }))
    await waitFor(() => expect(createRun).toHaveBeenCalled())
    expect(vi.mocked(createRun).mock.calls[0][1]).toMatchObject({ mode: 'prefer', target_values: ['polished'], protected_keys: ['dial_color'] })
    await waitFor(() => expect(runStore.get().active?.runId).toBe('r1'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('shape attributes are not listed', () => {
    const attrs = makeAttrs()
    const shape = { key: 'silhouette', label: 'Silhouette', category: 'case', kind: 'shape' }
    setup({ attrs: { ...attrs, lens: { ...attrs.lens!, attributes: [...attrs.lens!.attributes, shape] } } })
    expect(screen.getByRole('button', { name: /Date window/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Silhouette/ })).toBeNull()
  })

  it('locked: actions disabled with a hint', () => {
    setup({ params: { key: 'case_finish' }, explorations: [exploration([opt({ id: 'o1' })])], locked: true })
    expect(screen.getByText(/Demo — read-only/)).toBeTruthy()
    for (const name of ['Visualize Option o1', 'Branch Option o1', 'Dismiss Option o1', 'More', 'Further']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    }
  })
})
