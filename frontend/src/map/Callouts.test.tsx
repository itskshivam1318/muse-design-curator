import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisView, DimensionView, PartView } from '../api'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  extractPart: vi.fn(() => Promise.resolve({})),
  addDimension: vi.fn(() => Promise.resolve({})),
  addPart: vi.fn(() => Promise.resolve({})),
  removeDimension: vi.fn(() => Promise.resolve()),
  removePart: vi.fn(() => Promise.resolve()),
}))
const { extractPart, addDimension, addPart, removeDimension, removePart } = await import('../api')
const { Callouts } = await import('./Callouts')
const { partAnchor } = await import('./regions')
const { buildScene } = await import('../living/scene')
const { WHOLE: WHOLE_KEY } = await import('./cards')
const { createLivingWorld } = await import('../living/world')
const { LivingProvider } = await import('../living/useLiving')

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const part = (over: Partial<PartView> & { key: string }): PartView => ({
  label: over.key, region_kind: 'mask', region: null, mask_url: null, source: 'ai', ...over,
})
const dim = (over: Partial<DimensionView> & { key: string }): DimensionView => ({
  label: over.key, type: 'physical', part: null, prompt: null, kind: 'enum', value: null, confidence: 0.9,
  source: 'ai', status: 'extracted', ...over,
})

const analysis: AnalysisView = {
  content_type: 'image',
  parse_status: 'completed',
  parts: [
    part({ key: 'hands', label: 'Hands', region: [0.4, 0.2, 0.6, 0.5] }),
    part({ key: 'strap', label: 'Strap', region_kind: 'box', region: [0, 0.7, 0.3, 1] }),
  ],
  dimensions: [
    dim({ key: 'hand_style', label: 'Hand style', part: 'hands', value: 'syringe' }),
    dim({ key: 'strap_colour', label: 'Strap colour', part: 'strap', value: 'black_leather' }),
    dim({ key: 'lume', label: 'Lume', part: 'hands', value: 'green', status: 'stale' }),
    dim({ key: 'mood', label: 'Mood', type: 'abstract', value: 'sporty' }),
  ],
}

const item = makeItem({ id: 'i1', board_id: 'b1', x: 0, y: 0, w: 400, h: 300 })
const view = { x: 0, y: 0, scale: 1 }

function setup(
  over: {
    onOpenDimension?: (key: string) => void
    onHoverPart?: (key: string | null) => void
    locked?: boolean
    item?: typeof item
    analysis?: AnalysisView
  } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const onOpenDimension = over.onOpenDimension ?? vi.fn()
  const onHoverPart = over.onHoverPart ?? vi.fn()
  const target = over.item ?? item
  const a = over.analysis ?? analysis
  // the selected item's callouts are bodies of the world, ringed around it
  let t = 0
  let cb: FrameRequestCallback | null = null
  const world = createLivingWorld({ reduced: true, now: () => t, schedule: (f) => ((cb = f), 1), cancel: () => {} })
  const frame = () => {
    t += 1000 / 60
    act(() => cb?.(t))
  }
  world.sync(
    buildScene({ items: [target], explorations: [], analyses: new Map([[target.id, a]]), labels: new Map(), collapsed: () => false, selectedId: target.id }),
    -1000,
  )
  render(
    <QueryClientProvider client={qc}>
      <LivingProvider world={world}>
        <Callouts item={target} analysis={a} view={view} onOpenDimension={onOpenDimension} onHoverPart={onHoverPart} locked={over.locked} />
      </LivingProvider>
    </QueryClientProvider>,
  )
  return { qc, onOpenDimension, onHoverPart, world, frame }
}

const card = (name: string) => screen.getByRole('group', { name })

describe('Callouts', () => {
  it('renders one callout per part and a Whole item card for abstract dimensions', () => {
    setup()
    const hands = card('Hands')
    expect(within(hands).getByText('SAM mask')).toBeTruthy()
    expect(within(hands).getByRole('button', { name: 'Hand style · syringe' })).toBeTruthy()
    expect(within(hands).getByRole('button', { name: 'Extract' })).toBeTruthy()
    expect(within(hands).getByRole('button', { name: '+ Add dimension' })).toBeTruthy()
    const strap = card('Strap')
    expect(within(strap).getByText('box')).toBeTruthy()
    expect(within(strap).getByRole('button', { name: 'Strap colour · black leather' })).toBeTruthy()
    const whole = card('Whole item')
    expect(whole.className).toContain('is-whole')
    expect(within(whole).getByText('no mask')).toBeTruthy()
    expect(within(whole).getByRole('button', { name: 'Mood · sporty' })).toBeTruthy()
    expect(within(whole).queryByRole('button', { name: 'Extract' })).toBeNull()
    expect(within(whole).getByRole('button', { name: '+ Add part' })).toBeTruthy()
    // a physical dimension sits only on its part
    expect(within(whole).queryByRole('button', { name: /Hand style/ })).toBeNull()
    // one leader line and anchor dot per part, none for the whole item
    expect(document.querySelectorAll('.callout-leader')).toHaveLength(2)
    expect(document.querySelectorAll('.callout-anchor')).toHaveLength(2)
  })

  it("each card sits where its body is; a part's leader runs from its anchor to the card", () => {
    const { world } = setup()
    const body = world.body('callout:i1:hands')!
    const hands = card('Hands')
    const r2 = (n: number) => Math.round(n * 100) / 100
    expect(hands.style.transform).toContain(`translate(${r2(body.x - body.w / 2)}px, ${r2(body.y - body.h / 2)}px)`)
    expect(hands.style.left).toBe('')
    const leader = document.querySelector('.callout-leader')!
    const anchor = partAnchor({ x: 0, y: 0, width: 400, height: 300 }, analysis.parts[0])
    expect([leader.getAttribute('x1'), leader.getAttribute('y1')]).toEqual([String(anchor.x), String(anchor.y)])
    expect(Number(leader.getAttribute('x2'))).toBeGreaterThanOrEqual(r2(body.x - body.w / 2) - 0.01) // written to 2 decimals
  })

  it('leaders at rest are not rewritten each frame', () => {
    const { world, frame } = setup()
    world.start()
    for (let i = 0; i < 400; i++) frame()
    const els = [...document.querySelectorAll<SVGElement>('.callout-leader, .callout-anchor')]
    const writes = els.map((el) => vi.spyOn(el, 'setAttribute'))
    frame()
    expect(writes.reduce((n, w) => n + w.mock.calls.length, 0)).toBe(0)
  })

  it('a callout with an error message reports a taller height, so its body grows to fit it', async () => {
    // jsdom has no layout: a card is 80 tall, 40 more with an error in it
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('callout') ? 80 + (this.querySelector('[role="alert"]') ? 40 : 0) : 0
    })
    vi.mocked(extractPart).mockRejectedValueOnce(new Error('No luck'))
    const onHeights = vi.fn()
    const qc = new QueryClient()
    const world = createLivingWorld({ reduced: true })
    render(
      <QueryClientProvider client={qc}>
        <LivingProvider world={world}>
          <Callouts item={item} analysis={analysis} view={view} onHoverPart={vi.fn()} onHeights={onHeights} />
        </LivingProvider>
      </QueryClientProvider>,
    )
    expect(onHeights).toHaveBeenLastCalledWith({ hands: 80, strap: 80, [WHOLE_KEY]: 80 })
    fireEvent.click(within(card('Strap')).getByRole('button', { name: 'Extract' }))
    await waitFor(() => expect(onHeights).toHaveBeenLastCalledWith({ hands: 80, strap: 120, [WHOLE_KEY]: 80 }))
  })

  it('hovering a callout or one of its dimensions reports the part; leaving clears it', () => {
    const { onHoverPart } = setup()
    fireEvent.mouseEnter(card('Hands'))
    expect(onHoverPart).toHaveBeenLastCalledWith('hands')
    fireEvent.mouseLeave(card('Hands'))
    expect(onHoverPart).toHaveBeenLastCalledWith(null)
    fireEvent.focus(screen.getByRole('button', { name: 'Strap colour · black leather' }))
    expect(onHoverPart).toHaveBeenLastCalledWith('strap')
  })

  it('clicking a dimension opens it', () => {
    const { onOpenDimension } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Hand style · syringe' }))
    expect(onOpenDimension).toHaveBeenCalledWith('hand_style')
  })

  it('Extract calls extractPart with the part key', async () => {
    setup()
    fireEvent.click(within(card('Strap')).getByRole('button', { name: 'Extract' }))
    await waitFor(() => expect(extractPart).toHaveBeenCalledWith('i1', 'strap'))
  })

  it('× on a dimension removes it from the item and refreshes the analysis', async () => {
    const { qc } = setup()
    const refresh = vi.spyOn(qc, 'invalidateQueries')
    fireEvent.click(within(card('Whole item')).getByRole('button', { name: 'Remove Mood' }))
    await waitFor(() => expect(removeDimension).toHaveBeenCalledWith('i1', 'mood'))
    await waitFor(() => expect(refresh).toHaveBeenCalledWith({ queryKey: ['analysis', 'i1'] }))
  })

  it('Remove on a part asks once, then removes the part', async () => {
    setup()
    const hands = card('Hands')
    fireEvent.click(within(hands).getByRole('button', { name: 'Remove' }))
    expect(removePart).not.toHaveBeenCalled()
    fireEvent.click(within(hands).getByRole('button', { name: 'Cancel' }))
    expect(within(hands).queryByRole('button', { name: 'Remove part' })).toBeNull()
    fireEvent.click(within(hands).getByRole('button', { name: 'Remove' }))
    fireEvent.click(within(hands).getByRole('button', { name: 'Remove part' }))
    await waitFor(() => expect(removePart).toHaveBeenCalledWith('i1', 'hands'))
    // the Whole item card is not a part: nothing to remove
    expect(within(card('Whole item')).queryByRole('button', { name: 'Remove' })).toBeNull()
  })

  it('stale dimension is shown greyed with its explanation', () => {
    setup()
    const lume = screen.getByRole('button', { name: 'Lume · green' })
    expect(lume.className).toContain('is-stale')
    expect(lume.getAttribute('title')).toBe('old dimension, not found on this item')
    const hand = screen.getByRole('button', { name: 'Hand style · syringe' })
    expect(hand.className).not.toContain('is-stale')
    // labels are one line (ellipsis): the full text is in the title
    expect(hand.getAttribute('title')).toBe('Hand style · syringe')
  })

  it('+ Add dimension and + Add part label the item', async () => {
    setup()
    fireEvent.click(within(card('Hands')).getByRole('button', { name: '+ Add dimension' }))
    const input = within(card('Hands')).getByRole('textbox', { name: 'New dimension on Hands' })
    fireEvent.change(input, { target: { value: 'Hand length' } })
    fireEvent.submit(input)
    await waitFor(() =>
      expect(addDimension).toHaveBeenCalledWith('i1', { label: 'Hand length', type: 'physical', part: 'hands' }),
    )
    fireEvent.click(within(card('Whole item')).getByRole('button', { name: '+ Add dimension' }))
    const abstract = within(card('Whole item')).getByRole('textbox', { name: 'New dimension on Whole item' })
    fireEvent.change(abstract, { target: { value: 'Era' } })
    fireEvent.submit(abstract)
    await waitFor(() => expect(addDimension).toHaveBeenCalledWith('i1', { label: 'Era', type: 'abstract', part: null }))
    fireEvent.click(screen.getByRole('button', { name: '+ Add part' }))
    const newPart = screen.getByRole('textbox', { name: 'New part' })
    fireEvent.change(newPart, { target: { value: 'Crown' } })
    fireEvent.submit(newPart)
    await waitFor(() => expect(addPart).toHaveBeenCalledWith('i1', { label: 'Crown' }))
  })

  it('+ Add part is offered on images only: not on a note nor on a UI screenshot', () => {
    setup({ item: makeItem({ ...item, kind: 'note', note_text: 'A tall jar' }), analysis: { ...analysis, parts: [], content_type: 'text' } })
    expect(within(card('Whole item')).queryByRole('button', { name: '+ Add part' })).toBeNull()
    expect(within(card('Whole item')).getByRole('button', { name: '+ Add dimension' })).toBeTruthy()
    cleanup()
    setup({ analysis: { ...analysis, content_type: 'ui' } })
    expect(within(card('Whole item')).queryByRole('button', { name: '+ Add part' })).toBeNull()
    cleanup()
    setup({ item: makeItem({ ...item, kind: 'video' }) })
    expect(within(card('Whole item')).getByRole('button', { name: '+ Add part' })).toBeTruthy()
  })

  it('locked: nothing that changes the item is enabled', () => {
    setup({ locked: true })
    expect((within(card('Strap')).getByRole('button', { name: 'Extract' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '+ Add part' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Hand style · syringe' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Remove Mood' }) as HTMLButtonElement).disabled).toBe(true)
    expect((within(card('Strap')).getByRole('button', { name: 'Remove' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('partAnchor', () => {
  const b = { x: 100, y: 100, width: 400, height: 300 }
  it('is the region centre for a located part, else the item centre', () => {
    expect(partAnchor(b, part({ key: 'a', region_kind: 'box', region: [0, 0, 0.5, 0.5] }))).toEqual({ x: 200, y: 175 })
    expect(partAnchor(b, part({ key: 'a', region: null }))).toEqual({ x: 300, y: 250 })
  })

  it('a passage anchors at the note edge, at the height of its text', () => {
    const p = part({ key: 'a', region_kind: 'text_range', region: [50, 100] })
    const a = partAnchor(b, p, 'x'.repeat(100))
    expect(a.x).toBeGreaterThan(b.x + (b.width * 2) / 3)
    expect(a.y).toBe(b.y + b.height * 0.75)
  })
})
