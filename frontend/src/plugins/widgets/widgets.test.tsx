import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys, type Item } from '../../api'
import { makeItem } from '../../test/fixtures'

vi.mock('../../api', async (orig) => ({ ...(await orig<typeof import('../../api')>()), describeNode: vi.fn() }))
const api = await import('../../api')
const { Segmented } = await import('./Segmented')
const { SeedButton } = await import('./SeedButton')
const { PaletteField } = await import('./PaletteField')
const { PartColors } = await import('./PartColors')
const { FrameSlot } = await import('./FrameSlot')
const { PromptField } = await import('./PromptField')

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Segmented', () => {
  it('saves the chosen enum (numbers for an integer enum)', () => {
    const save = vi.fn()
    const { rerender } = render(<Segmented id="s" label="Mode" options={['a', 'b']} value="a" onSave={save} />)
    fireEvent.click(screen.getByRole('radio', { name: 'b' }))
    expect(save).toHaveBeenCalledWith('b')
    rerender(<Segmented id="s" label="Duration" options={['5', '10']} numeric value={5} onSave={save} />)
    fireEvent.click(screen.getByRole('radio', { name: '10' }))
    expect(save).toHaveBeenLastCalledWith(10)
  })
})

describe('SeedButton', () => {
  it('saves a new integer different from the current', () => {
    const save = vi.fn()
    render(<SeedButton id="s" value={7} onSave={save} />)
    fireEvent.click(screen.getByRole('button', { name: 'Shuffle' }))
    const n = save.mock.calls[0][0]
    expect(Number.isInteger(n)).toBe(true)
    expect(n).not.toBe(7)
  })
})

describe('PaletteField', () => {
  it('lists presets and board palettes, edits one swatch, copies the hex list', async () => {
    const save = vi.fn()
    const writeText = vi.fn(() => Promise.resolve())
    Object.assign(navigator, { clipboard: { writeText } })
    const presets = [{ name: 'Warm', colors: ['#ff0000', '#ffaa00'] }]
    render(
      <PaletteField
        id="p"
        value={{ name: 'Warm', colors: ['#ff0000', '#ffaa00'] }}
        presets={presets}
        boardPalettes={[['#ff0000', '#ffaa00'], ['#112233', '#445566'], ['#112233', '#445566']]}
        onSave={save}
      />,
    )
    expect(screen.getByRole('button', { name: 'Preset Warm' })).toBeTruthy()
    // the duplicate of the preset and the repeated board palette collapse to one
    expect(screen.getAllByRole('button', { name: /Board palette/ })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Board palette 1' }))
    expect(save).toHaveBeenLastCalledWith({ name: 'Board', colors: ['#112233', '#445566'] })
    fireEvent.change(screen.getByLabelText('Colour 2'), { target: { value: '#00ff00' } })
    expect(save).toHaveBeenLastCalledWith({ name: 'Custom', colors: ['#ff0000', '#00ff00'] })
    fireEvent.click(screen.getByRole('button', { name: 'Copy hex' }))
    expect(writeText).toHaveBeenCalledWith('#ff0000, #ffaa00')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeTruthy())
  })
})

function withQc(node: ReactNode, setup?: (qc: QueryClient) => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  setup?.(qc)
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>
}

describe('PartColors', () => {
  it("lists the input item's mask parts by label and saves {key: hex}", () => {
    const save = vi.fn()
    const part = (key: string, label: string, region_kind: 'mask' | 'box') => ({ key, label, region_kind, region: null, mask_url: null, source: 'x' })
    render(
      withQc(<PartColors id="c" itemId="i1" value={{ strap: '#111111' }} onSave={save} />, (qc) =>
        qc.setQueryData(keys.analysis('i1'), {
          content_type: 'image', parse_status: 'completed', dimensions: [],
          parts: [part('strap', 'Strap', 'mask'), part('dial', 'Dial', 'mask'), part('box', 'Region', 'box')],
        }),
      ),
    )
    expect(screen.queryByText('Region')).toBeNull()
    fireEvent.change(screen.getByLabelText('Dial colour'), { target: { value: '#00ff00' } })
    expect(save).toHaveBeenCalledWith({ strap: '#111111', dial: '#00ff00' })
  })
})

describe('FrameSlot', () => {
  const a = makeItem({ id: 'a', original_filename: 'a.png' })
  const b = makeItem({ id: 'b', original_filename: 'b.png' })
  const note = makeItem({ id: 'n', kind: 'note' })
  const items = new Map<string, Item>([a, b, note].map((i) => [i.id, i]))
  it('accepts a picked or dropped image item id; swap is offered', () => {
    const save = vi.fn()
    const swap = vi.fn()
    const { container } = render(<FrameSlot id="f" label="First frame" value="a" items={items} onSave={save} onSwap={swap} />)
    fireEvent.change(screen.getByLabelText('First frame'), { target: { value: 'b' } })
    expect(save).toHaveBeenLastCalledWith('b')
    const drop = (id: string) => fireEvent.drop(container.firstElementChild!, { dataTransfer: { getData: () => id } })
    drop('b')
    expect(save).toHaveBeenCalledTimes(2)
    drop('n') // a note is not an image
    drop('zzz')
    expect(save).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: 'Swap' }))
    expect(swap).toHaveBeenCalled()
  })
})

describe('PromptField', () => {
  it('Describe fills the text from describeNode and is disabled while locked', async () => {
    vi.mocked(api.describeNode).mockResolvedValue({ prompt: 'A red watch' })
    const save = vi.fn()
    const { rerender } = render(<PromptField id="p" nodeId="n1" value="" describe onSave={save} />)
    fireEvent.click(screen.getByRole('button', { name: 'Describe' }))
    await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('A red watch'))
    expect(api.describeNode).toHaveBeenCalledWith('n1')
    expect(save).toHaveBeenCalledWith('A red watch')
    rerender(<PromptField id="p" nodeId="n1" value="" describe readOnly onSave={save} />)
    expect((screen.getByRole('button', { name: 'Describe' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
