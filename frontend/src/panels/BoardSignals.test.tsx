import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { keys } from '../api'
import { applyEvent } from '../events'
import { makeItem, makeProfile } from '../test/fixtures'
import { BoardSignals } from './BoardSignals'

afterEach(cleanup)

function setup(items = [] as ReturnType<typeof makeItem>[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), items)
  qc.setQueryData(keys.lens('b1'), null)
  qc.setQueryData(keys.profile('b1'), {
    version: 1,
    profile: makeProfile({
      n_reference: 9,
      signals: [{ key: 'case_finish', label: 'Case finish', kind: 'enum', modal_value: 'brushed_steel', consistency: 7 / 9, n_known: 9 }],
    }),
  })
  render(
    <QueryClientProvider client={qc}>
      <BoardSignals boardId="b1" />
    </QueryClientProvider>,
  )
  return qc
}

describe('BoardSignals', () => {
  it('counts board images only: never staged takes or notes', () => {
    setup([
      makeItem({ id: 'a', board_id: 'b1' }),
      makeItem({ id: 'b', board_id: 'b1', staged: true }),
      makeItem({ id: 'n', board_id: 'b1', kind: 'note', note_text: 'oak' }),
    ])
    expect(screen.getByText('Board · 1 item')).toBeTruthy()
  })

  it('renders signals as "value · n of N" rows', () => {
    setup()
    expect(screen.getByText('Brushed steel')).toBeTruthy()
    expect(screen.getByText('7 of 9')).toBeTruthy()
  })

  it('signals panel updates on profile.updated event', async () => {
    const qc = setup()
    act(() => {
      applyEvent(qc, 'b1', 'profile.updated', {
        version: 2,
        profile: makeProfile({
          n_reference: 10,
          attributes: {
            dial_color: { key: 'dial_color', label: 'Dial', kind: 'enum', n_known: 7, distribution: {}, modal_value: null, consistency: null, median: null, iqr: null, clusters: [], medoid_item_id: null, values: [] },
          },
          signals: [{ key: 'case_finish', label: 'Case finish', kind: 'enum', modal_value: 'brushed_steel', consistency: 0.8, n_known: 10 }],
          tensions: [{ key: 'dial_color', label: 'Dial', values: ['black', 'blue'], shares: [4 / 7, 3 / 7] }],
          counter_signals: [{ key: 'case_material', label: 'Case material', value: 'polished_gold', counter_count: 2, reference_count: 0 }],
        }),
      })
    })
    expect(await screen.findByText('8 of 10')).toBeTruthy()
    expect(screen.getByText('Dial: black 4 · blue 3')).toBeTruthy()
    expect(screen.getByText(/Polished gold/)).toBeTruthy()
    // the changed row is highlighted
    expect(screen.getByText('8 of 10').closest('[data-changed="true"]')).toBeTruthy()
  })

  it('ignores an older profile version', async () => {
    const qc = setup()
    act(() => {
      applyEvent(qc, 'b1', 'profile.updated', { version: 0, profile: makeProfile() })
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByText('7 of 9')).toBeTruthy()
  })
})
