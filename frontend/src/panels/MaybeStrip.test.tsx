import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys, type RunResponse } from '../api'
import { runResponse } from '../test/runs'
import { makeAttrs } from '../test/attrs'
import { runStore } from '../vary/runStore'

// the cache is the source of truth here; a refetch never settles
vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  getRun: vi.fn(() => new Promise(() => {})),
}))
const { MaybeStrip } = await import('./MaybeStrip')

afterEach(() => {
  cleanup()
  runStore.clear()
})

function setup(data: RunResponse) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.run('r1'), data)
  qc.setQueryData(keys.attributes('i1'), makeAttrs())
  runStore.start({
    boardId: 'b1', runId: 'r1',
    request: { source_item_id: 'i1', target_key: 'dial_color', mode: 'explore', target_values: [], protected_keys: [], nudge: null },
  })
  render(
    <QueryClientProvider client={qc}>
      <MaybeStrip boardId="b1" streamOpen />
    </QueryClientProvider>,
  )
  return qc
}

describe('MaybeStrip', () => {
  it('strip state bar not border', () => {
    setup(runResponse())
    const thumbs = screen.getAllByRole('button', { name: /^Candidate/ })
    expect(thumbs).toHaveLength(3)
    // validated first, then the Needs review divider, then uncertain
    const strip = screen.getByRole('region', { name: 'Maybe strip' })
    const order = [...strip.querySelectorAll('[data-state], .strip-divider')].map((n) =>
      n.classList.contains('strip-divider') ? 'divider' : n.getAttribute('data-state'))
    expect(order).toEqual(['validated', 'validated', 'divider', 'uncertain'])
    for (const t of thumbs) {
      const img = t.querySelector('img')!
      const bar = t.querySelector('.strip-bar')!
      // state lives in a bar UNDER the image, never as a frame around it
      expect(img.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(img.style.border).toBe('')
      expect(t.style.border).toBe('')
      expect(img.getAttribute('class') ?? '').not.toMatch(/border|outline|frame/)
    }
  })

  it('shows progress while checking', () => {
    setup(runResponse({
      run: { ...runResponse().run, status: 'validating' },
      progress: { stage: 'validating', validated_n: 8, shortlist_n: 16 },
      results: [], needs_review: [], summary: null,
    }))
    expect(screen.getByText('Checking 8 of 16')).toBeTruthy()
  })

  it('"Why only N?" opens the shortfall summary', () => {
    setup(runResponse())
    fireEvent.click(screen.getByRole('button', { name: 'Why only 2?' }))
    expect(screen.getByText('5 changed a protected attribute (Case finish)')).toBeTruthy()
  })

  it('empty and failed states use plain copy', async () => {
    const qc = setup(runResponse({ results: [], needs_review: [], summary: { ...runResponse().summary!, returned: 0 } }))
    expect(screen.getByText('Nothing passed every check. Most common reason: 5 changed a protected attribute (Case finish).')).toBeTruthy()
    act(() => {
      qc.setQueryData(keys.run('r1'), runResponse({
        run: { ...runResponse().run, status: 'failed', error_code: 'RUN_INTERRUPTED' }, results: [], needs_review: [],
      }))
    })
    expect(await screen.findByText(/This run failed: it was interrupted before it finished\./)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Run again' })).toBeTruthy()
  })
})
