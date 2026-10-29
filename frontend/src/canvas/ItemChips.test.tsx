import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AttributeSpec, type Exploration, type Item, keys } from '../api'
import { LENS, LENS_ATTRS, makeAttrs } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { chipSource, focusStore } from './axis'
import { selection } from './selection'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), exploreItem: vi.fn() }))
const { exploreItem } = await import('../api')
const { AxisPicker, ItemChips } = await import('./ItemChips')

const EXTRA: AttributeSpec[] = [
  { key: 'strap', label: 'Strap', category: 'strap', kind: 'text' },
  { key: 'lume', label: 'Lume', category: 'dial', kind: 'text' },
  { key: 'crown', label: 'Crown', category: 'case', kind: 'text' },
  { key: 'outline', label: 'Outline', category: 'case', kind: 'shape' },
]
const BIG_LENS = { ...LENS, attributes: [...LENS_ATTRS, ...EXTRA] }

function setup(item: Item, explorations: Exploration[] = []) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const attrs = makeAttrs()
  qc.setQueryData(keys.attributes(item.id), {
    ...attrs,
    lens: BIG_LENS,
    attributes: [
      ...attrs.attributes,
      ...EXTRA.map((s) => ({ ...attrs.attributes[0], key: s.key, label: s.label, kind: s.kind, value: 'x' })),
    ],
  })
  qc.setQueryData(keys.explorations('b1'), explorations)
  const screenBox = { x: 10, y: 10, width: 200, height: 150 }
  render(
    <QueryClientProvider client={qc}>
      <ItemChips item={item} screen={screenBox} />
    </QueryClientProvider>,
  )
  return qc
}

const image = makeItem({ id: 'i1', board_id: 'b1' })

beforeEach(() => vi.mocked(exploreItem).mockReset())
afterEach(() => {
  cleanup()
  selection.clear()
  focusStore.set(null)
})

describe('ItemChips', () => {
  it('shows at most 6 chips for the selected image, never shape attributes', () => {
    selection.select(['i1'])
    setup(image)
    const chips = screen.getAllByRole('button')
    expect(chips).toHaveLength(6)
    expect(chips.map((c) => c.getAttribute('data-key'))).not.toContain('outline')
  })

  it('shows nothing unless the image is the one selected item', () => {
    selection.select(['other'])
    setup(image)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    cleanup()
    selection.select(['n1'])
    setup(makeItem({ id: 'n1', board_id: 'b1', kind: 'note', note_text: 'hi' }))
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })

  it('a chip click explores that attribute and focuses its axis', async () => {
    const e: Exploration = { id: 'e9', board_id: 'b1', item_id: 'i1', key: 'case_finish', options: [] }
    vi.mocked(exploreItem).mockResolvedValue(e)
    selection.select(['i1'])
    const qc = setup(image)
    fireEvent.click(screen.getByRole('button', { name: /Case finish/ }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('i1', { key: 'case_finish', mode: 'initial' }))
    await waitFor(() => expect(focusStore.get()).toBe('e9'))
    expect(qc.getQueryData<Exploration[]>(keys.explorations('b1'))).toEqual([e])
  })

  it('a chip whose axis already has options only focuses it', () => {
    selection.select(['i1'])
    const live: Exploration = {
      id: 'e1', board_id: 'b1', item_id: 'i1', key: 'case_finish',
      options: [{ id: 'o1', exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: 'A', description: '', distance: 'near', value: 'a', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [], x: null, y: null }],
    }
    setup(image, [live])
    fireEvent.click(screen.getByRole('button', { name: /Case finish/ }))
    expect(exploreItem).not.toHaveBeenCalled()
    expect(focusStore.get()).toBe('e1')
  })

  it('each chip carries its source mark', () => {
    selection.select(['i1'])
    setup(image)
    expect(screen.getByRole('button', { name: /Dial colour/ }).querySelector('.chip-mark')?.getAttribute('data-source')).toBe('read')
  })
})

describe('chipSource', () => {
  const base = makeAttrs().attributes[0]
  it('maps attribute provenance onto the six marks', () => {
    expect(chipSource({ ...base, measured: { lab: [1, 2, 3] } })).toBe('measured')
    expect(chipSource(base)).toBe('read')
    expect(chipSource({ ...base, status: 'uncertain' })).toBe('estimated')
    expect(chipSource({ ...base, source: 'web' })).toBe('web')
    expect(chipSource({ ...base, source: 'user' })).toBe('you')
    expect(chipSource({ ...base, status: 'confirmed' })).toBe('you')
    expect(chipSource({ ...base, status: 'missing', value: null })).toBe('unknown')
  })
})

describe('AxisPicker', () => {
  it('lists the attributes and explores the picked one', async () => {
    vi.mocked(exploreItem).mockResolvedValue({ id: 'e5', board_id: 'b1', item_id: 'i1', key: 'legibility', options: [] })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    qc.setQueryData(keys.attributes('i1'), makeAttrs())
    qc.setQueryData(keys.explorations('b1'), [])
    const onDone = vi.fn()
    render(
      <QueryClientProvider client={qc}>
        <AxisPicker item={image} screen={{ x: 0, y: 0, width: 100, height: 100 }} onDone={onDone} />
      </QueryClientProvider>,
    )
    expect(screen.getByRole('dialog', { name: 'Pick an attribute to explore' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Legibility/ }))
    await waitFor(() => expect(exploreItem).toHaveBeenCalledWith('i1', { key: 'legibility', mode: 'initial' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(focusStore.get()).toBe('e5')
  })
})
