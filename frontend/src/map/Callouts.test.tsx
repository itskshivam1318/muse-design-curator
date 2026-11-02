import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisView, DimensionView, PartView } from '../api'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  extractPart: vi.fn(() => Promise.resolve({})),
  addDimension: vi.fn(() => Promise.resolve({})),
  addPart: vi.fn(() => Promise.resolve({})),
}))
const { extractPart, addDimension, addPart } = await import('../api')
const { Callouts } = await import('./Callouts')
const { partAnchor } = await import('./regions')

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

function setup(over: { onOpenDimension?: (key: string) => void; onHoverPart?: (key: string | null) => void; locked?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const onOpenDimension = over.onOpenDimension ?? vi.fn()
  const onHoverPart = over.onHoverPart ?? vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <Callouts item={item} analysis={analysis} view={view} onOpenDimension={onOpenDimension} onHoverPart={onHoverPart} locked={over.locked} />
    </QueryClientProvider>,
  )
  return { qc, onOpenDimension, onHoverPart }
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

  it('locked: nothing that changes the item is enabled', () => {
    setup({ locked: true })
    expect((within(card('Strap')).getByRole('button', { name: 'Extract' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '+ Add part' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Hand style · syringe' }) as HTMLButtonElement).disabled).toBe(true)
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
