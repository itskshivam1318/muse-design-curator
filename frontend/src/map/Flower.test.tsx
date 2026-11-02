import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useLayoutEffect, useMemo } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AnalysisView, ApiError, type Exploration, type ExploreOption, type Item, keys } from '../api'
import { rectsIntersect } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { LENS } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { isCollapsed } from './collapse'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  getRenderers: vi.fn(() => Promise.resolve([])),
  keepTake: vi.fn(),
  getAnalysis: vi.fn(() => new Promise(() => {})),
  listItems: vi.fn(() => new Promise(() => {})),
}))
const { keepTake, getAnalysis } = await import('../api')
const { FlowerLayer } = await import('./Flower')
const { useLivingScene } = await import('../living/useLivingScene')
const { createLivingWorld } = await import('../living/world')
const { LivingProvider } = await import('../living/useLiving')
const { Edges } = await import('../living/Edges')
const { useItems } = await import('../queries')

/** The canvas in small: the scene over the items, synced into a world, the layer drawing it. */
function Harness() {
  const all = useItems('b1').data
  const items = useMemo(() => (all ?? []).filter((i) => !i.staged), [all])
  const world = useMemo(() => createLivingWorld({ reduced: true }), [])
  const scene = useLivingScene('b1', items, null)
  useLayoutEffect(() => world.sync(scene), [world, scene])
  return (
    <LivingProvider world={world}>
      <Edges scene={scene} view={view} />
      <FlowerLayer boardId="b1" items={items} view={view} flowers={scene.flowers} />
    </LivingProvider>
  )
}

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

function setup(
  explorations: Exploration[],
  extra: { items?: Item[]; analysed?: string[] } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.demo, { demo_mode: false, explore_enabled: true })
  qc.setQueryData(keys.explorations('b1'), explorations)
  qc.setQueryData(keys.items('b1'), [a, b, ...(extra.items ?? [])])
  qc.setQueryData(keys.lens('b1'), { spec: LENS })
  const analysed = extra.analysed ?? ['a', 'b']
  if (analysed.includes('a')) qc.setQueryData(keys.analysis('a'), analysis('Hand style'))
  if (analysed.includes('b')) qc.setQueryData(keys.analysis('b'), analysis('Hand shape'))
  render(
    <QueryClientProvider client={qc}>
      <Harness />
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
    // a stem from each item to its hub
    expect(document.querySelectorAll('path[data-edge-kind="stem"]')).toHaveLength(2)
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
    // a kept option's take is docked in the ring in its place: no petal
    expect(petal('o4')).toBeNull()
    expect(petal('o5').className).toContain('is-drifted')
    expect(within(hub('Hand style')).getByText('5 options · 1 kept')).toBeTruthy()
  })

  it('a petal opens its card, focused, so Escape closes it at once', async () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
    fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
    const card = screen.getByRole('dialog', { name: 'Copper' })
    expect(within(card).getByTestId('petal-scope').textContent).toBe('Changes Hands · keeps 0 ✓')
    expect(await within(card).findByRole('button', { name: /Connect a renderer/ })).toBeTruthy()
    expect(document.activeElement).toBe(card)
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('an open card stays in the viewport and clear of the agent card', () => {
    const rect = (x: number, y: number, width: number, height: number) =>
      ({ x, y, left: x, top: y, width, height, right: x + width, bottom: y + height, toJSON: () => ({}) }) as DOMRect
    const agent = document.createElement('aside')
    agent.className = 'agent-card'
    document.body.appendChild(agent)
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('flower-layer')) return rect(0, 0, 500, 500)
      if (this.classList.contains('agent-card')) return rect(232, 380, 252, 104)
      if (this.classList.contains('petal-card-anchor')) return rect(0, 0, 260, 300)
      return rect(0, 0, 0, 0)
    })
    try {
      setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
      fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
      const anchor = document.querySelector<HTMLElement>('.petal-card-anchor')!
      const [left, top] = [parseFloat(anchor.style.left), parseFloat(anchor.style.top)]
      expect(left).toBeGreaterThanOrEqual(8)
      expect(top).toBeGreaterThanOrEqual(8)
      expect(left + 260).toBeLessThanOrEqual(500 - 8)
      expect(top + 300).toBeLessThanOrEqual(500 - 8)
      expect(rectsIntersect({ x: left, y: top, width: 260, height: 300 }, { x: 232, y: 380, width: 252, height: 104 })).toBe(false)
    } finally {
      spy.mockRestore()
      agent.remove()
    }
  })

  it('an open card never covers its own petal (clicking the petal again closes it)', () => {
    const rect = (x: number, y: number, width: number, height: number) =>
      ({ x, y, left: x, top: y, width, height, right: x + width, bottom: y + height, toJSON: () => ({}) }) as DOMRect
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('flower-layer')) return rect(0, 0, 500, 500)
      if (this.classList.contains('petal-card-anchor')) return rect(0, 0, 260, 300)
      // the petal spans the layer's top: the card has to go below it
      if (this.classList.contains('petal')) return rect(0, 0, 500, 180)
      return rect(0, 0, 0, 0)
    })
    try {
      setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
      fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
      const anchor = document.querySelector<HTMLElement>('.petal-card-anchor')!
      expect(parseFloat(anchor.style.top)).toBeGreaterThanOrEqual(188)
    } finally {
      spy.mockRestore()
    }
  })

  it('an open card lifts the flower layer above the callouts (their cards would cover it)', () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
    const layer = document.querySelector('.flower-layer')!
    expect(layer.classList.contains('has-card')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
    expect(layer.classList.contains('has-card')).toBe(true)
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Copper' }), { key: 'Escape' })
    expect(layer.classList.contains('has-card')).toBe(false)
  })

  it('collapses to a badge on its callout and opens again; the flag is kept per board', () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' }), opt({ id: 'o2', status: 'kept', kept_item_id: 'k' })] }])
    fireEvent.click(within(hub('Hand style')).getByRole('button', { name: 'Collapse Hand style' }))
    expect(screen.queryByTestId('petal')).toBeNull()
    expect(isCollapsed('b1', 'e1')).toBe(true)
    const badge = screen.getByRole('button', { name: 'Hand style · 2 options · 1 kept' })
    fireEvent.click(badge)
    expect(screen.getAllByTestId('petal')).toHaveLength(1) // o2 is kept (its take is not on the board)
    expect(isCollapsed('b1', 'e1')).toBe(false)
  })

  describe('flowers wait for the analyses they start from', () => {
    const onA = (id: string, over: Partial<Exploration> = {}) => ({ id, board_id: 'b1', item_id: 'a', key: 'hand_style', options: [opt({ id: `${id}-o`, exploration_id: id })], ...over })
    const onB = (id: string) => ({ id, board_id: 'b1', item_id: 'b', key: 'hand_style', options: [opt({ id: `${id}-o`, exploration_id: id })] })
    const drawn = () => screen.queryAllByTestId('petal').map((p) => p.dataset.optionId).sort()

    it('a flower on an item still loading waits; the others draw', () => {
      setup([onB('e1'), onA('e2')], { analysed: ['a'] })
      expect(drawn()).toEqual(['e2-o'])
    })

    it('a flower with a stored offset draws at once, its analysis loading or not', () => {
      setup([onA('e1', { dx: 300, dy: 0 })], { analysed: [] })
      expect(drawn()).toEqual(['e1-o'])
    })

    it('an analysis that fails settles: its flower draws', async () => {
      vi.mocked(getAnalysis).mockImplementation((id) => (id === 'b' ? Promise.reject(new ApiError(500, 'BOOM', 'Server error')) : new Promise(() => {})))
      setup([onB('e1'), onA('e2')], { analysed: ['a'] })
      expect(drawn()).toEqual(['e2-o'])
      // one retry, then it settles as failed
      await waitFor(() => expect(drawn()).toEqual(['e1-o', 'e2-o']), { timeout: 4000 })
    })
  })

  it('a kept result lands in free space beside its petal, clear of the items', async () => {
    const t1 = makeItem({
      id: 't1', board_id: 'b1', origin: 'generated', staged: true, explore_option_id: 'o1', parent_item_id: 'a', w: 200, h: 150,
      check: { target: { answer: 'yes', confidence: 1, note: '' }, kept: 1, of: 1, drifted: [] },
    })
    const o1 = opt({ id: 'o1', name: 'Copper', status: 'visualized', takes: ['t1'] })
    vi.mocked(keepTake).mockResolvedValue({ ...o1, status: 'kept', kept_item_id: 't1' })
    setup(
      [
        { id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', options: [o1, opt({ id: 'o2' }), opt({ id: 'o3' })] },
        { id: 'e2', board_id: 'b1', item_id: 'b', key: 'hand_style', options: [opt({ id: 'o4', exploration_id: 'e2' })] },
      ],
      { items: [t1] },
    )
    fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(keepTake).toHaveBeenCalled())
    const at = vi.mocked(keepTake).mock.calls[0][2]!
    const slot = { x: at.x, y: at.y, width: 200, height: 150 }
    for (const i of [a, b]) expect(rectsIntersect(slot, itemBounds(i))).toBe(false)
  })
})
