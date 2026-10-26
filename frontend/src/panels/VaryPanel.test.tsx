import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, keys } from '../api'
import { makeAttrs } from '../test/attrs'
import { makeItem, makeProfile } from '../test/fixtures'
import { runStore } from '../vary/runStore'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), createRun: vi.fn() }))
const { createRun } = await import('../api')
const { VaryPanel } = await import('./VaryPanel')

afterEach(() => {
  cleanup()
  runStore.clear()
})

function setup(params?: Record<string, unknown>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), [makeItem({ id: 'i1', board_id: 'b1' })])
  qc.setQueryData(keys.attributes('i1'), makeAttrs())
  qc.setQueryData(keys.profile('b1'), {
    version: 1,
    profile: makeProfile({
      signals: [{ key: 'legibility', label: 'Legibility', kind: 'ordinal', modal_value: 'medium', consistency: 0.8, n_known: 5 }],
      tensions: [{ key: 'case_diameter', label: 'Case diameter', values: ['38', '42'], shares: [0.5, 0.5] }],
    }),
  })
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <VaryPanel boardId="b1" itemId="i1" params={params} onClose={onClose} />
    </QueryClientProvider>,
  )
  return { qc, onClose }
}

describe('VaryPanel', () => {
  it('lists tensions first among targets', () => {
    setup()
    const targets = screen.getAllByRole('radio', { name: /colour|finish|legibility|diameter|window/i })
    expect(targets[0].textContent).toMatch(/Case diameter/)
  })

  it('nudge only offered for ordinal/number', () => {
    setup()
    fireEvent.click(screen.getByRole('radio', { name: /Case finish/ }))
    expect(screen.queryByRole('radio', { name: /^More/ })).toBeNull()
    expect(screen.getByRole('radio', { name: 'Explore' })).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: /Legibility/ }))
    fireEvent.click(screen.getByRole('radio', { name: /^More/ }))
    // the scale shows the current and the target step
    const scale = within(screen.getByRole('list', { name: 'Scale' }))
    expect(scale.getByText('medium').closest('[data-step]')?.getAttribute('data-step')).toBe('current')
    expect(scale.getByText('high').closest('[data-step]')?.getAttribute('data-step')).toBe('target')
    // two steps more would leave the scale: disabled
    expect((screen.getByRole('radio', { name: '2 steps' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('preflight sentence lists target, mode and protected', () => {
    setup({ targetKey: 'dial_color', mode: 'prefer', values: ['navy'] })
    // protected chips: board signal (legibility) first, then lens order; the target is never protected
    const chips = screen.getAllByRole('button', { name: /^Unprotect/ })
    expect(chips.map((c) => c.getAttribute('aria-label'))).toEqual([
      'Unprotect Legibility', 'Unprotect Case finish', 'Unprotect Case diameter', 'Unprotect Date window',
    ])
    expect(screen.getByText(
      'Prefer Dial colour navy, keeping Legibility, Case finish, Case diameter and Date window unchanged.',
    )).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Unprotect Case finish' }))
    expect(screen.getByText('Prefer Dial colour navy, keeping Legibility, Case diameter and Date window unchanged.')).toBeTruthy()
  })

  it('posts the request with a fresh Idempotency-Key and shows a 422 message verbatim', async () => {
    const spy = vi.mocked(createRun)
      .mockRejectedValueOnce(new ApiError(422, 'PREFER_EQUALS_CURRENT', 'The source already has that Dial colour.'))
      .mockResolvedValueOnce({ run_id: 'r1' })
    const { onClose } = setup({ targetKey: 'dial_color', mode: 'prefer', values: ['black'] })
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(await screen.findByText('The source already has that Dial colour.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    const [board, body, key1] = spy.mock.calls[0]
    const key2 = spy.mock.calls[1][2]
    expect(board).toBe('b1')
    expect(body).toMatchObject({ source_item_id: 'i1', target_key: 'dial_color', mode: 'prefer', target_values: ['black'], nudge: null })
    expect(body.protected_keys[0]).toBe('legibility')
    expect(key1).not.toBe(key2)
    expect(runStore.get().active?.runId).toBe('r1')
  })
})
