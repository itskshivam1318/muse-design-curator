import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { type AnalysisView, type DimensionView, type Item, keys } from '../api'
import { selection } from '../canvas/selection'
import { makeItem } from '../test/fixtures'
import { InspectPanel } from './InspectPanel'
import { inspectGroups } from './inspectGroups'

afterEach(() => {
  cleanup()
  selection.reset()
})

const dim = (d: Partial<DimensionView> & Pick<DimensionView, 'key' | 'label'>): DimensionView => ({
  type: d.part ? 'physical' : 'abstract', part: null, prompt: null, kind: 'text', value: null,
  confidence: null, source: 'ai', status: 'current', ...d,
})

const analysis = (a: Partial<AnalysisView> = {}): AnalysisView => ({
  content_type: 'image',
  parse_status: 'completed',
  parts: [{ key: 'trousers', label: 'wide pinstripe trousers', region_kind: 'mask', region: null, mask_url: null, source: 'ai' }],
  dimensions: [
    dim({ key: 'fabric', label: 'Fabric', part: 'trousers', value: 'wool' }),
    dim({ key: 'case_finish', label: 'Case finish', value: 'brushed', source: 'user' }),
    dim({ key: 'mood', label: 'Mood', status: 'stale' }),
  ],
  ...a,
})

function setup(item: Partial<Item> = {}, explorations?: unknown[], a: AnalysisView = analysis()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), [makeItem({ id: 'i1', board_id: 'b1', ...item })])
  qc.setQueryData(keys.explorations('b1'), explorations ?? [])
  qc.setQueryData(keys.analysis('i1'), a)
  render(
    <QueryClientProvider client={qc}>
      <InspectPanel boardId="b1" itemId="i1" onClose={() => {}} />
    </QueryClientProvider>,
  )
  return qc
}

describe('inspectGroups', () => {
  it('puts physical dimensions under their part and the rest under Whole item', () => {
    const groups = inspectGroups(analysis({
      dimensions: [
        dim({ key: 'fabric', label: 'Fabric', part: 'trousers' }),
        dim({ key: 'orphan', label: 'Orphan', part: 'gone' }),
        dim({ key: 'mood', label: 'Mood' }),
      ],
    }))
    expect(groups.map((g) => [g.title, g.dims.map((d) => d.key)])).toEqual([
      ['wide pinstripe trousers', ['fabric']],
      ['Whole item', ['orphan', 'mood']],
    ])
  })

  it('no whole-item group when every dimension sits on a part', () => {
    const groups = inspectGroups(analysis({ dimensions: [dim({ key: 'fabric', label: 'Fabric', part: 'trousers' })] }))
    expect(groups.map((g) => g.title)).toEqual(['wide pinstripe trousers'])
  })
})

describe('InspectPanel', () => {
  const generated = {
    origin: 'generated',
    generation: { model: 'img-1', prompt: 'a navy dial', option_id: 'o1' },
    explore_option_id: 'o1',
    check: { target: { answer: 'yes' as const, confidence: 1, note: '' }, kept: 3, of: 4 },
  }

  it("shows the item's own parts and dimensions, never a board lens", () => {
    setup()
    expect(screen.getByRole('heading', { name: 'wide pinstripe trousers' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Whole item' })).toBeTruthy()
    expect(screen.getByText('Fabric')).toBeTruthy()
    expect(screen.getByText('wool')).toBeTruthy()
    expect(screen.getByText(/edited by you/)).toBeTruthy()
    expect(screen.getByText(/stale/)).toBeTruthy()
    expect(screen.queryByText('Case shape')).toBeNull()
  })

  it('while the item is still being read it says so', () => {
    setup({}, [], analysis({ parse_status: 'processing', parts: [], dimensions: [] }))
    expect(screen.getByText(/Still reading this item/)).toBeTruthy()
    expect(screen.queryByText('Nothing was found on this item.')).toBeNull()
  })

  it('a failed analysis names its error code', () => {
    setup({ parse_error_code: 'REGION_EMPTY' }, [], analysis({ parse_status: 'failed', parts: [], dimensions: [] }))
    expect(screen.getByText('Analysis failed (REGION_EMPTY).')).toBeTruthy()
  })

  it('a generated item shows where it came from, its verdict, model and prompt, and no credit', () => {
    setup({ ...generated, rights_status: 'licensed', licence: { credit: 'c', license_code: 'X', license_url: null, creator_name: null, landing_url: null, source: 's' } },
      [{ id: 'e1', board_id: 'b1', item_id: 'i1', key: 'case_finish', options: [{ id: 'o1', name: 'Polished' }] }])
    expect(screen.getByText('Generated from Polished')).toBeTruthy()
    expect(screen.getByText('Case finish → Polished ✓ · 3 of 4 kept')).toBeTruthy()
    expect(screen.getByText(/img-1/)).toBeTruthy()
    expect(screen.getByText(/a navy dial/)).toBeTruthy()
    expect(screen.queryByRole('note', { name: 'Image credit' })).toBeNull()
  })

  it('with the option not found it falls back to a neutral heading and verdict', () => {
    setup(generated, [])
    expect(screen.getByText('Generated image')).toBeTruthy()
    expect(screen.getByText('✓ · 3 of 4 kept')).toBeTruthy()
  })

  it('a licensed item shows its stored credit in the header', () => {
    setup({
      rights_status: 'licensed',
      licence: {
        credit: 'Photo by Ana B, CC BY 4.0', license_code: 'CC-BY-4.0',
        license_url: 'https://creativecommons.org/licenses/by/4.0/', creator_name: 'Ana B',
        landing_url: 'https://commons.wikimedia.org/wiki/File:W.jpg', source: 'wikimedia',
      },
    })
    const cap = screen.getByRole('note', { name: 'Image credit' })
    expect(cap.textContent).toBe('© Ana B · CC-BY-4.0 · Source ↗')
    expect(screen.getByRole('link', { name: 'Source ↗' }).getAttribute('href')).toBe('https://commons.wikimedia.org/wiki/File:W.jpg')
  })

  it('a user item shows no credit line', () => {
    setup()
    expect(screen.queryByRole('note', { name: 'Image credit' })).toBeNull()
  })
})
