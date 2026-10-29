import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Board } from '../api'
import { ItemToolbar } from '../canvas/ItemToolbar'
import { makeItem } from '../test/fixtures'
import { AddActions } from './AddMenu'
import { ContextBar } from './ContextBar'
import { DemoBadge } from './DemoBadge'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

function withQuery(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('DemoBadge', () => {
  it('renders nothing when the server is not in demo mode', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ demo_mode: false, unlocked: true }))
    const { container } = withQuery(<DemoBadge />)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/demo/status', expect.anything()))
    expect(container.textContent).toBe('')
  })

  it('locked demo: shows the read-only chip; the passcode dialog shows server errors, then unlocks', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json({ demo_mode: true, unlocked: false }))
      .mockResolvedValueOnce(json({ error: { code: 'DEMO_PASSCODE_INVALID', message: 'That passcode is not right.' } }, 401))
      .mockResolvedValueOnce(json({ demo_mode: true, unlocked: true }))
    withQuery(<DemoBadge />)
    expect(await screen.findByText('Demo — read-only')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }))
    const dialog = screen.getByRole('dialog', { name: 'Unlock the demo' })
    const input = screen.getByLabelText('Passcode')
    expect(document.activeElement).toBe(input)
    fireEvent.change(input, { target: { value: 'wrong' } })
    fireEvent.submit(dialog)
    expect((await screen.findByRole('alert')).textContent).toBe('That passcode is not right.')
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/demo/unlock',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ passcode: 'wrong' }) }),
    )

    fireEvent.change(input, { target: { value: 'right' } })
    fireEvent.submit(dialog)
    expect(await screen.findByText('Demo — unlocked')).toBeTruthy()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Unlock' })).toBeNull()
  })

  it('shows the rate-limit message from the server', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json({ demo_mode: true, unlocked: false }))
      .mockResolvedValueOnce(
        json({ error: { code: 'DEMO_RATE_LIMITED', message: 'Too many wrong passcodes. Try again in 9 minutes.' } }, 429),
      )
    withQuery(<DemoBadge />)
    fireEvent.click(await screen.findByRole('button', { name: 'Unlock' }))
    fireEvent.change(screen.getByLabelText('Passcode'), { target: { value: 'x' } })
    fireEvent.submit(screen.getByRole('dialog'))
    expect((await screen.findByRole('alert')).textContent).toBe('Too many wrong passcodes. Try again in 9 minutes.')
  })
})

describe('locked controls', () => {
  const board: Board = {
    id: 'b1', title: 'T', context: 'c', domain: null, lens_id: null, created_at: '', updated_at: '',
  }

  it('add actions are disabled and never open', () => {
    render(<AddActions onFiles={() => {}} onLink={async () => {}} disabled />)
    for (const name of [/upload images or video/i, /paste a link/i, /get the chrome extension/i]) {
      const b = screen.getByRole('button', { name }) as HTMLButtonElement
      expect(b.disabled).toBe(true)
      fireEvent.click(b)
    }
    expect(screen.queryByLabelText('Link to a page or image')).toBeNull()
  })

  it('toolbar keeps Vary and Inspect but disables Not this and Remove', () => {
    const noop = () => {}
    render(
      <ItemToolbar items={[makeItem()]} screen={{ x: 0, y: 100, width: 100, height: 100 }} onExplore={noop}
        onInspect={noop} onCompare={noop} onNotThis={noop} onRemove={noop} readOnly />,
    )
    const disabled = (name: string) => (screen.getByRole('button', { name }) as HTMLButtonElement).disabled
    expect(disabled('Not this')).toBe(true)
    expect(disabled('Remove')).toBe(true)
  })

  it('context bar: title read-only, brief editor disabled, badge shown', () => {
    const onSave = vi.fn()
    render(<ContextBar board={board} profile={undefined} onSave={onSave} locked badge={<span>BADGE</span>} />)
    expect((screen.getByLabelText('Board title') as HTMLInputElement).readOnly).toBe(true)
    expect((screen.getByRole('button', { name: /Auto/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('BADGE')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Board title'), { target: { value: 'New' } })
    fireEvent.blur(screen.getByLabelText('Board title'))
    expect(onSave).not.toHaveBeenCalled()
  })
})
