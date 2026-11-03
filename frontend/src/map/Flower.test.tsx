import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useLayoutEffect, useMemo } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AnalysisView, ApiError, type Exploration, type ExploreOption, type Item, keys, type Point } from '../api'
import { type Bounds, rectsIntersect } from '../canvas/geometry'
import { KEPT_EXTRA, petalAngles, petalRadius } from '../living/ring'
import { LENS } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { isCollapsed, setCollapsed } from './collapse'

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

/** What the harness exposes to a test: its world, and the hub releases it was handed. */
const harness = {
  world: null as ReturnType<typeof createLivingWorld> | null,
  released: [] as Map<string, Point>[],
  rerender: null as ((viewport?: Bounds) => void) | null,
}

/** The canvas in small: the scene over the items, synced into a world, the layer drawing it. */
function Harness({ viewport }: { viewport?: Bounds }) {
  const all = useItems('b1').data
  const items = useMemo(() => (all ?? []).filter((i) => !i.staged), [all])
  const world = useMemo(() => createLivingWorld({ reduced: true }), [])
  useLayoutEffect(() => {
    harness.world = world
  }, [world])
  const scene = useLivingScene('b1', items, null)
  useLayoutEffect(() => world.sync(scene), [world, scene])
  return (
    <LivingProvider world={world}>
      <Edges scene={scene} view={view} />
      <FlowerLayer boardId="b1" items={items} view={view} flowers={scene.flowers} viewport={viewport} onRelease={(c) => harness.released.push(c)} />
    </LivingProvider>
  )
}

function opt(over: Partial<ExploreOption> & { id: string }): ExploreOption {
  return {
    exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: `Option ${over.id}`, description: '',
    distance: 'near', value: 'v', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null, undocked: false,
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
  extra: { items?: Item[]; analysed?: string[]; viewport?: Bounds } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.demo, { demo_mode: false, explore_enabled: true })
  qc.setQueryData(keys.explorations('b1'), explorations)
  qc.setQueryData(keys.items('b1'), [a, b, ...(extra.items ?? [])])
  qc.setQueryData(keys.lens('b1'), { spec: LENS })
  const analysed = extra.analysed ?? ['a', 'b']
  if (analysed.includes('a')) qc.setQueryData(keys.analysis('a'), analysis('Hand style'))
  if (analysed.includes('b')) qc.setQueryData(keys.analysis('b'), analysis('Hand shape'))
  const tree = (viewport?: Bounds) => (
    <QueryClientProvider client={qc}>
      <Harness viewport={viewport} />
    </QueryClientProvider>
  )
  const { rerender } = render(tree(extra.viewport))
  harness.rerender = (viewport) => rerender(tree(viewport))
  return qc
}

const hub = (label: string) => screen.getByRole('group', { name: `${label} flower` })

beforeEach(() => {
  localStorage.clear()
  harness.released = []
})
afterEach(cleanup)

describe('FlowerLayer', () => {
  it('two flowers open at once both render', () => {
    setup([
      { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' }), opt({ id: 'o2' }), opt({ id: 'o3', status: 'dismissed' })] },
      { id: 'e2', board_id: 'b1', dx: null, dy: null, item_id: 'b', key: 'hand_style', options: [opt({ id: 'o4', exploration_id: 'e2' })] },
    ])
    expect(within(hub('Hand style')).getByText('Hand style')).toBeTruthy()
    expect(within(hub('Hand style')).getByText('2 options · 0 kept')).toBeTruthy()
    expect(within(hub('Hand style')).getAllByTestId('petal').map((p) => p.dataset.optionId)).toEqual(['o1', 'o2'])
    expect(within(hub('Hand shape')).getByText('1 options · 0 kept')).toBeTruthy()
    // a stem from each item to its hub
    expect(document.querySelectorAll('path[data-edge-kind="stem"]')).toHaveLength(2)
  })

  it('only flowers near the viewport mount; panning to one mounts it', () => {
    const exps: Exploration[] = [
      { id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' })] },
      { id: 'e2', board_id: 'b1', dx: null, dy: null, item_id: 'b', key: 'hand_style', options: [opt({ id: 'o2', exploration_id: 'e2' })] },
    ]
    // around item a; item b and its hub sit 1200 below, past half a viewport's margin
    setup(exps, { viewport: { x: -100, y: -100, width: 600, height: 400 } })
    expect(screen.queryByRole('group', { name: 'Hand style flower' })).toBeTruthy()
    expect(screen.queryByRole('group', { name: 'Hand shape flower' })).toBeNull()
    act(() => harness.rerender!({ x: -100, y: 1100, width: 600, height: 400 }))
    expect(screen.queryByRole('group', { name: 'Hand shape flower' })).toBeTruthy()
    expect(screen.queryByRole('group', { name: 'Hand style flower' })).toBeNull()
    // freshly mounted, it is placed at once
    const p = document.querySelector<HTMLElement>('[data-option-id="o2"]')!
    expect(p.style.transform).toMatch(/translate/)
  })

  it('petals show their state: note, rendering, rendered, kept and drifted', () => {
    const shot = (id: string, drifted: string[] = []) =>
      makeItem({ id, board_id: 'b1', origin: 'generated', staged: true, explore_option_id: 'x', check: { target: { answer: 'yes', confidence: 1, note: '' }, kept: 1, of: 1, drifted } })
    setup(
      [
        {
          id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', dx: null, dy: null,
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
    // one is rendering: the hub says so instead of its counts
    expect(within(hub('Hand style')).getByText('rendering 1…')).toBeTruthy()
  })

  it('a petal opens its card, focused, so Escape closes it at once', async () => {
    setup([{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
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
      setup([{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
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
      setup([{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
      fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
      const anchor = document.querySelector<HTMLElement>('.petal-card-anchor')!
      expect(parseFloat(anchor.style.top)).toBeGreaterThanOrEqual(188)
    } finally {
      spy.mockRestore()
    }
  })

  it('an open card lifts the flower layer above the callouts (their cards would cover it)', () => {
    setup([{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1', name: 'Copper' })] }])
    const layer = document.querySelector('.flower-layer')!
    expect(layer.classList.contains('has-card')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
    expect(layer.classList.contains('has-card')).toBe(true)
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Copper' }), { key: 'Escape' })
    expect(layer.classList.contains('has-card')).toBe(false)
  })

  it('dragging the hub moves its body and hands its centre to onRelease; a press without movement is a click', () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', dx: 300, dy: 0, options: [opt({ id: 'o1' })] }])
    const el = document.querySelector<HTMLElement>('.flower-hub')!
    const collapse = within(hub('Hand style')).getByRole('button', { name: 'Collapse Hand style' })
    const at = { ...harness.world!.body('hub:e1')! }
    fireEvent.pointerDown(collapse, { button: 0, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(collapse, { clientX: 12, clientY: 11 }) // under the threshold: not yet a drag
    expect(harness.world!.body('hub:e1')!.x).toBe(at.x)
    fireEvent.pointerMove(el, { clientX: 60, clientY: 30 })
    expect([harness.world!.body('hub:e1')!.x, harness.world!.body('hub:e1')!.y]).toEqual([at.x + 50, at.y + 20])
    expect(el.hasAttribute('data-dragging')).toBe(true) // it shows the grabbing hand
    fireEvent.pointerUp(el, { clientX: 60, clientY: 30 })
    expect(el.hasAttribute('data-dragging')).toBe(false)
    expect(harness.released).toEqual([new Map([['hub:e1', { x: at.x + 50, y: at.y + 20 }]])])
    fireEvent.click(collapse) // the click that ends the drag does not collapse
    expect(isCollapsed('b1', 'e1')).toBe(false)
    expect(harness.released).toHaveLength(1)
  })

  it('a drag that ends with no click does not swallow the next real click', async () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', dx: 300, dy: 0, options: [opt({ id: 'o1' })] }])
    const el = document.querySelector<HTMLElement>('.flower-hub')!
    const collapse = within(hub('Hand style')).getByRole('button', { name: 'Collapse Hand style' })
    fireEvent.pointerDown(el, { button: 0, clientX: 10, clientY: 10 })
    fireEvent.pointerMove(el, { clientX: 60, clientY: 30 })
    fireEvent.pointerUp(el, { clientX: 60, clientY: 30 })
    await new Promise((r) => setTimeout(r, 0))
    fireEvent.click(collapse)
    expect(isCollapsed('b1', 'e1')).toBe(true)
    setCollapsed('b1', 'e1', false)
  })

  it('a press without movement on the collapse button is still a click', () => {
    setup([{ id: 'e1', board_id: 'b1', item_id: 'a', key: 'hand_style', dx: 300, dy: 0, options: [opt({ id: 'o1' })] }])
    const collapse = within(hub('Hand style')).getByRole('button', { name: 'Collapse Hand style' })
    fireEvent.pointerDown(collapse, { button: 0, clientX: 10, clientY: 10 })
    fireEvent.pointerUp(collapse, { clientX: 10, clientY: 10 })
    fireEvent.click(collapse)
    expect(isCollapsed('b1', 'e1')).toBe(true)
    expect(harness.released).toEqual([])
    setCollapsed('b1', 'e1', false)
  })

  it('collapses to a badge on its callout and opens again; the flag is kept per board', () => {
    setup([{ id: 'e1', board_id: 'b1', dx: null, dy: null, item_id: 'a', key: 'hand_style', options: [opt({ id: 'o1' }), opt({ id: 'o2', status: 'kept', kept_item_id: 'k' })] }])
    fireEvent.click(within(hub('Hand style')).getByRole('button', { name: 'Collapse Hand style' }))
    expect(screen.queryByTestId('petal')).toBeNull()
    expect(isCollapsed('b1', 'e1')).toBe(true)
    const badge = screen.getByRole('button', { name: 'Hand style · 2 options · 1 kept' })
    fireEvent.click(badge)
    expect(screen.getAllByTestId('petal')).toHaveLength(1) // o2 is kept (its take is not on the board)
    expect(isCollapsed('b1', 'e1')).toBe(false)
  })

  describe('flowers wait for the analyses they start from', () => {
    const onA = (id: string, over: Partial<Exploration> = {}): Exploration => ({ id, board_id: 'b1', item_id: 'a', key: 'hand_style', dx: null, dy: null, options: [opt({ id: `${id}-o`, exploration_id: id })], ...over })
    const onB = (id: string) => ({ id, board_id: 'b1', item_id: 'b', key: 'hand_style', dx: null, dy: null, options: [opt({ id: `${id}-o`, exploration_id: id })] })
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

  it('keep sends the docked size and slot', async () => {
    const t1 = makeItem({
      id: 't1', board_id: 'b1', origin: 'generated', staged: true, explore_option_id: 'o1', parent_item_id: 'a', w: 200, h: 150,
      check: { target: { answer: 'yes', confidence: 1, note: '' }, kept: 1, of: 1, drifted: [] },
    })
    const o1 = opt({ id: 'o1', name: 'Copper', status: 'visualized', takes: ['t1'] })
    vi.mocked(keepTake).mockResolvedValue({ ...o1, status: 'kept', kept_item_id: 't1' })
    const qc = setup(
      [{ id: 'e1', board_id: 'b1', dx: 300, dy: 0, item_id: 'a', key: 'hand_style', options: [o1, opt({ id: 'o2' }), opt({ id: 'o3' })] }],
      { items: [t1] },
    )
    // the hub has been dragged: the slot follows it where it is now, not its stored home
    const world = harness.world!
    act(() => world.place('hub:e1', { x: 400, y: 300 }))
    const pulse = vi.spyOn(world, 'pulse')
    fireEvent.click(screen.getByRole('button', { name: /Copper/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(keepTake).toHaveBeenCalled())
    // o1 is the first of 3 petals: its slot is on the ring past the petals, opening from the source (100, 75) through the hub
    const src = world.body('a')!
    const angle = petalAngles(Math.atan2(300 - src.y, 400 - src.x), 3)[0]
    const r = petalRadius(3) + KEPT_EXTRA
    const slot = { x: 400 + Math.cos(angle) * r, y: 300 + Math.sin(angle) * r }
    const at = { x: Math.round(slot.x - 84), y: Math.round(slot.y - 63) }
    expect(vi.mocked(keepTake).mock.calls[0]).toEqual(['o1', 't1', at, { w: 168, h: 126 }])
    // on the board at once, docked size, and it swells as it lands
    await waitFor(() => expect(qc.getQueryData<Item[]>(keys.items('b1'))!.find((i) => i.id === 't1')).toMatchObject({ ...at, w: 168, h: 126, staged: false }))
    await waitFor(() => expect(pulse).toHaveBeenCalledWith('t1'))
  })
})
