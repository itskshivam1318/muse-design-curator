import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type Item, keys } from '../api'
import { makeAttrs } from '../test/attrs'
import { makeItem } from '../test/fixtures'
import { cand } from '../test/runs'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), postDecision: vi.fn() }))
const { postDecision } = await import('../api')
const { CandidatePopover } = await import('./CandidatePopover')

afterEach(cleanup)

const source = makeItem({ id: 'i1', board_id: 'b1', x: 100, y: 50, w: 200, h: 150 })

function setup(onKept = vi.fn(), provenance?: Partial<ReturnType<typeof cand>['provenance']>, onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), [source])
  qc.setQueryData(keys.attributes('i1'), makeAttrs())
  const c = cand('c1', 'validated', {
    ...(provenance ? { provenance: { ...cand('x', 'validated').provenance, ...provenance } } : {}),
    checks: [
      { check: 'target', attribute_key: 'dial_color', verdict: 'pass', reason: 'Dial colour changed: #1B1D22 → #2F55C4 (ΔE 38)', evidence: { values: { source: 'black', candidate: 'navy', delta_e: 38 } } },
      { check: 'protected', attribute_key: 'legibility', verdict: 'uncertain', reason: 'Legibility is too uncertain to call', evidence: { values: { source: 'medium', candidate: 'high' } } },
      { check: 'protected', attribute_key: 'case_finish', verdict: 'fail', reason: 'Case finish changed: brushed → polished', evidence: null },
    ],
  })
  render(
    <QueryClientProvider client={qc}>
      <CandidatePopover boardId="b1" runId="r1" candidate={c} sourceItemId="i1" targetKey="dial_color" onClose={onClose} onKept={onKept} />
    </QueryClientProvider>,
  )
  return { qc, onKept, onClose }
}

function originOf(over: Partial<ReturnType<typeof cand>>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), [source])
  qc.setQueryData(keys.attributes('i1'), makeAttrs())
  render(
    <QueryClientProvider client={qc}>
      <CandidatePopover boardId="b1" runId="r1" candidate={cand('c1', 'validated', over)} sourceItemId="i1" targetKey="dial_color" onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('CandidatePopover origin', () => {
  it('says where a live find came from', () => {
    originOf({ origin: 'live', source: 'openverse' })
    expect(screen.getByText('Found live on Openverse')).toBeTruthy()
  })
  it('says a corpus candidate is from the library', () => {
    originOf({ origin: 'corpus' })
    expect(screen.getByText('From your library')).toBeTruthy()
  })
})

describe('CandidatePopover', () => {
  it('shows credit, source link, target change and checks with per-kind visuals', () => {
    setup()
    expect(screen.getByText(/Photo by A/)).toBeTruthy()
    const link = screen.getByRole('link', { name: /Source/ })
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(screen.getByText('black → navy')).toBeTruthy()
    const checks = screen.getByRole('list', { name: 'Checks' })
    expect(checks.textContent).toContain('✓')
    expect(checks.textContent).toContain('?')
    expect(checks.textContent).toContain('✕')
    expect(checks.querySelectorAll('.swatch')).toHaveLength(2)
    expect(checks.querySelector('.mini-scale')).toBeTruthy()
  })

  it('keep adds item to canvas next to source', async () => {
    const kept: Item = makeItem({ id: 'k1', board_id: 'b1', origin: 'candidate', parent_item_id: 'i1', x: 324, y: 50 })
    vi.mocked(postDecision).mockResolvedValue({ decision: { id: 'd1', decision: 'keep', reason_code: null, note: null, item_id: 'k1', created_at: '' }, history: [], item: kept })
    const { qc, onKept } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(onKept).toHaveBeenCalled())
    const [runId, candId, body, key] = vi.mocked(postDecision).mock.calls[0]
    expect([runId, candId, body]).toEqual(['r1', 'c1', { decision: 'keep' }])
    expect(typeof key).toBe('string')
    const items = qc.getQueryData<Item[]>(keys.items('b1'))!
    const added = items.find((i) => i.id === 'k1')!
    expect(added.parent_item_id).toBe('i1')
    expect(added.x).toBeGreaterThanOrEqual(source.x + source.w)
    expect(added.y).toBe(source.y)
    expect(onKept.mock.calls[0][0].id).toBe('k1')
  })

  it('reject sends a reason, a note and Mark as not this', async () => {
    vi.mocked(postDecision).mockResolvedValue({ decision: { id: 'd2', decision: 'reject', reason_code: 'not_my_style', note: 'too shiny', item_id: null, created_at: '' }, history: [], item: null })
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Not my style' }))
    fireEvent.change(screen.getByLabelText(/Note/), { target: { value: 'too shiny' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Mark as not this' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reject' }))
    await waitFor(() => expect(postDecision).toHaveBeenCalled())
    expect(vi.mocked(postDecision).mock.calls[0][2]).toEqual({ decision: 'reject', reason_code: 'not_my_style', note: 'too shiny', mark_not_this: true })
  })
})

describe('CandidatePopover safety and keyboard', () => {
  it('does not render a Source link for a non-http(s) landing URL', () => {
    for (const bad of ['javascript:alert(1)', 'data:text/html,x', '/relative', 'not a url']) {
      setup(vi.fn(), { landing_url: bad })
      expect(screen.queryByRole('link', { name: /Source/ })).toBeNull()
      expect(screen.getByText(/Photo by A/)).toBeTruthy() // the credit still shows
      cleanup()
    }
  })

  it('is a modal dialog: focus on Keep, Tab trapped, Escape from the note closes it', () => {
    const { onClose } = setup()
    const dlg = screen.getByRole('dialog', { name: 'Candidate' })
    expect(dlg.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Keep' }))
    fireEvent.keyDown(document.activeElement!, { key: 'Tab' })
    expect(dlg.contains(document.activeElement)).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'Wrong change' }))
    const note = screen.getByLabelText(/Note/)
    note.focus()
    fireEvent.change(note, { target: { value: 'x' } })
    expect(document.activeElement).toBe(note) // re-render does not steal focus
    fireEvent.keyDown(note, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
