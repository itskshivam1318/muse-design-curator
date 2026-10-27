import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

  it('reads as a live search, then as checking', async () => {
    const qc = setup(runResponse({
      run: { ...runResponse().run, status: 'retrieving' },
      progress: { stage: 'searching', live: { sources: {}, searching: ['commons', 'met', 'aic'], found: 23 } },
      results: [], needs_review: [], summary: null,
    }))
    expect(screen.getByText('Searching Wikimedia Commons, the Met, … (found 23)')).toBeTruthy()
    act(() => {
      qc.setQueryData(keys.run('r1'), runResponse({
        run: { ...runResponse().run, status: 'validating' },
        progress: { stage: 'validating', validated_n: 8, shortlist_n: 16, live: { sources: { commons: 'ok', met: 'failed' }, found: 23 } },
        results: [], needs_review: [], summary: null,
      }))
    })
    expect(await screen.findByText('Checking 8 of 16')).toBeTruthy()
    const chips = screen.getByLabelText('Live sources')
    expect(chips.textContent).toContain('Wikimedia Commons')
    expect(chips.querySelector('[data-status="failed"]')?.textContent).toContain('the Met')
  })

  it('offers Pinterest and Google Images searches for the run, opening in a new tab', () => {
    const base = runResponse()
    setup(runResponse({
      summary: { ...base.summary!, live: { queries: ['watch arabic numerals', 'watch dial'], found: 3, kept: 1, sources: { commons: 'ok' } } },
    }))
    const pin = screen.getByRole('link', { name: 'Pinterest ↗' })
    expect(pin.getAttribute('href')).toBe('https://www.pinterest.com/search/pins/?q=watch%20arabic%20numerals')
    expect(pin.getAttribute('target')).toBe('_blank')
    expect(pin.getAttribute('rel')).toContain('noopener')
    expect(screen.getByRole('link', { name: 'Google Images ↗' }).getAttribute('href')).toContain('udm=2')
  })

  it('"Why only N?" shows each live source and whether it answered', () => {
    const base = runResponse()
    setup(runResponse({
      summary: {
        ...base.summary!,
        live: { queries: ['q'], found: 12, kept: 1, sources: { commons: 'ok', openverse: 'failed' } },
        shortfall: [{ code: 'source_failed', count: 1, message: "Openverse didn't respond" }],
      },
    }))
    fireEvent.click(screen.getByRole('button', { name: 'Why only 2?' }))
    const dialog = screen.getByLabelText('Why fewer results')
    expect(dialog.textContent).toContain("Openverse didn't respond")
    expect(dialog.textContent).toContain('Wikimedia Commons: searched')
    expect(dialog.textContent).toContain('Found 12 live, 1 kept')
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

describe('MaybeStrip dialogs', () => {
  it('candidate popover returns focus to its thumbnail on Escape', async () => {
    setup(runResponse())
    const thumb = screen.getAllByRole('button', { name: /^Candidate/ })[0]
    thumb.focus()
    fireEvent.click(thumb)
    const dlg = await screen.findByRole('dialog', { name: 'Candidate' })
    expect(dlg.contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Candidate' })).toBeNull())
    expect(document.activeElement).toBe(thumb)
  })

  it('"Why only N?" is a modal dialog that closes on Escape and restores focus', () => {
    setup(runResponse())
    const why = screen.getByRole('button', { name: 'Why only 2?' })
    why.focus()
    fireEvent.click(why)
    const dlg = screen.getByRole('dialog', { name: 'Why fewer results' })
    expect(dlg.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }))
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Why fewer results' })).toBeNull()
    expect(document.activeElement).toBe(why)
  })
})
