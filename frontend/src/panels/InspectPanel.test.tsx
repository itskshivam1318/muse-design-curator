import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type Item, keys } from '../api'
import { selection, selectionStore } from '../canvas/selection'
import { makeAttrs } from '../test/attrs'
import { makeItem, makeProfile } from '../test/fixtures'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  patchAttribute: vi.fn(async (_id: string, key: string, body: Record<string, unknown>) => ({
    ...makeAttrs().attributes.find((a) => a.key === key)!,
    ...('value' in body ? { value: body.value, status: 'edited', source: 'user' } : {}),
    ...(body.action === 'confirm' ? { status: 'confirmed' } : {}),
    ...(body.action === 'disable' ? { enabled: false } : {}),
  })),
}))
const { patchAttribute } = await import('../api')
const { InspectPanel } = await import('./InspectPanel')

afterEach(() => {
  cleanup()
  selection.reset()
  vi.useRealTimers()
})

function setup(locked = false, item: Partial<Item> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.items('b1'), [makeItem({ id: 'i1', board_id: 'b1', ...item })])
  qc.setQueryData(keys.attributes('i1'), makeAttrs({ case_finish: { status: 'edited', source: 'user' } }))
  qc.setQueryData(keys.profile('b1'), {
    version: 1,
    profile: makeProfile({ signals: [{ key: 'legibility', label: 'Legibility', kind: 'ordinal', modal_value: 'medium', consistency: 0.8, n_known: 5 }] }),
  })
  render(
    <QueryClientProvider client={qc}>
      <InspectPanel boardId="b1" itemId="i1" onClose={() => {}} locked={locked} />
    </QueryClientProvider>,
  )
  return qc
}

describe('InspectPanel', () => {
  it('a licensed item shows its stored credit in the header', () => {
    setup(false, {
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

  it('locked demo: values are shown but every editor is disabled', () => {
    setup(true)
    expect(screen.getByText('Demo — read-only: unlock to edit values.')).toBeTruthy()
    const row = screen.getByRole('group', { name: 'Legibility' })
    const controls = row.querySelectorAll<HTMLInputElement | HTMLButtonElement>('input, select, button[role="radio"]')
    expect(controls.length).toBeGreaterThan(0)
    for (const c of controls) expect(c.matches(':disabled')).toBe(true)
    expect((screen.getByRole('button', { name: 'Vary Legibility' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('groups rows by category with status chips and board signal marks', () => {
    setup()
    expect(screen.getByRole('heading', { name: 'Dial' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Case' })).toBeTruthy()
    const legibility = screen.getByRole('group', { name: 'Legibility' })
    expect(legibility.textContent).toContain('board signal')
    expect(screen.getByRole('group', { name: 'Case finish' }).textContent).toContain('edited by you')
  })

  it('per-kind editors PATCH typed values', async () => {
    setup()
    fireEvent.click(screen.getByRole('radio', { name: 'medium' })) // already the value: no PATCH
    fireEvent.click(screen.getByRole('button', { name: 'Increase Case diameter' }))
    fireEvent.click(screen.getByRole('radio', { name: 'high' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Date window value' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Case finish value' }), { target: { value: 'polished' } })
    await waitFor(() => expect(patchAttribute).toHaveBeenCalledTimes(4))
    const calls = vi.mocked(patchAttribute).mock.calls.map((c) => [c[1], c[2]])
    expect(calls).toEqual([
      ['case_diameter', { value: 41 }],
      ['legibility', { value: 'high' }],
      ['date_window', { value: true }],
      ['case_finish', { value: 'polished' }],
    ])
    expect(await screen.findAllByText('edited by you')).toBeTruthy()
  })

  it('confirm, disable and Vary this', async () => {
    const qc = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Dial colour' }))
    await waitFor(() => expect(patchAttribute).toHaveBeenCalledWith('i1', 'dial_color', { action: 'confirm' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Use Dial colour' }))
    await waitFor(() => expect(patchAttribute).toHaveBeenCalledWith('i1', 'dial_color', { action: 'disable' }))
    await act(async () => {})
    expect(qc.getQueryData<{ attributes: { key: string; enabled: boolean }[] }>(keys.attributes('i1'))!
      .attributes.find((a) => a.key === 'dial_color')!.enabled).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Vary Legibility' }))
    expect(selectionStore.get().drawer).toEqual({ kind: 'vary', itemId: 'i1', params: { targetKey: 'legibility' } })
  })
})

describe('TextEditor', () => {
  it('debounces typing into one PATCH', async () => {
    vi.useFakeTimers()
    const { TextEditor } = await import('./InspectPanel')
    const onCommit = vi.fn()
    render(<TextEditor name="Era value" value="1960s" onCommit={onCommit} />)
    const input = screen.getByRole('textbox', { name: 'Era value' })
    fireEvent.change(input, { target: { value: '1970' } })
    act(() => vi.advanceTimersByTime(300))
    fireEvent.change(input, { target: { value: '1970s' } })
    act(() => vi.advanceTimersByTime(300))
    expect(onCommit).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(400))
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('1970s')
  })

  it('flushes a pending edit on unmount instead of dropping it', async () => {
    vi.useFakeTimers()
    const { TextEditor } = await import('./InspectPanel')
    const onCommit = vi.fn()
    const { unmount } = render(<TextEditor name="Era value" value="1960s" onCommit={onCommit} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Era value' }), { target: { value: '1980s' } })
    expect(onCommit).not.toHaveBeenCalled()
    unmount()
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith('1980s')
    act(() => vi.advanceTimersByTime(2000))
    expect(onCommit).toHaveBeenCalledTimes(1) // the cleared timer does not fire it again
  })

  it('does not commit on unmount when nothing changed', async () => {
    const { TextEditor } = await import('./InspectPanel')
    const onCommit = vi.fn()
    render(<TextEditor name="Era value" value="1960s" onCommit={onCommit} />).unmount()
    expect(onCommit).not.toHaveBeenCalled()
  })
})
