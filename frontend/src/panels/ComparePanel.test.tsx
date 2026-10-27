import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { keys } from '../api'
import { selection, selectionStore } from '../canvas/selection'
import { makeAttrs } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { ComparePanel } from './ComparePanel'

afterEach(() => {
  cleanup()
  selection.reset()
})

describe('ComparePanel', () => {
  it('compare shows only differing attributes', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    qc.setQueryData(keys.items('b1'), [makeItem({ id: 'i1' }), makeItem({ id: 'i2' })])
    qc.setQueryData(keys.attributes('i1'), makeAttrs())
    qc.setQueryData(keys.attributes('i2'), makeAttrs({ dial_color: { value: 'navy' }, case_diameter: { value: 42 } }))
    render(
      <QueryClientProvider client={qc}>
        <ComparePanel boardId="b1" itemId="i1" params={{ itemIds: ['i1', 'i2'] }} onClose={() => {}} />
      </QueryClientProvider>,
    )
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows.map((r) => r.querySelector('th')?.textContent)).toEqual(['Dial colour', 'Case diameter'])
    expect(screen.queryByText('Case finish')).toBeNull()
    fireEvent.click(screen.getAllByRole('button', { name: /Vary toward this/ })[0])
    expect(selectionStore.get().drawer).toEqual({
      kind: 'vary', itemId: 'i1', params: { targetKey: 'dial_color', mode: 'prefer', values: ['navy'] },
    })
  })

  it('offers "Vary toward this" relative to any picked source item', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    qc.setQueryData(keys.items('b1'), [makeItem({ id: 'i1' }), makeItem({ id: 'i2' }), makeItem({ id: 'i3' })])
    qc.setQueryData(keys.attributes('i1'), makeAttrs())
    qc.setQueryData(keys.attributes('i2'), makeAttrs({ dial_color: { value: 'navy' } }))
    qc.setQueryData(keys.attributes('i3'), makeAttrs({ dial_color: { value: 'green' } }))
    render(
      <QueryClientProvider client={qc}>
        <ComparePanel boardId="b1" itemId="i1" params={{ itemIds: ['i1', 'i2', 'i3'] }} onClose={() => {}} />
      </QueryClientProvider>,
    )
    const picker = screen.getByRole('combobox', { name: 'Vary source' }) as HTMLSelectElement
    expect(picker.value).toBe('i1') // defaults to the first
    expect(screen.getAllByRole('button', { name: /Vary toward this/ })).toHaveLength(2)
    fireEvent.change(picker, { target: { value: 'i2' } })
    const buttons = screen.getAllByRole('button', { name: /Vary toward this/ })
    expect(buttons).toHaveLength(2) // i1 (black) and i3 (green) differ from i2 (navy)
    fireEvent.click(buttons[0])
    expect(selectionStore.get().drawer).toEqual({
      kind: 'vary', itemId: 'i2', params: { targetKey: 'dial_color', mode: 'prefer', values: ['black'] },
    })
  })
})
